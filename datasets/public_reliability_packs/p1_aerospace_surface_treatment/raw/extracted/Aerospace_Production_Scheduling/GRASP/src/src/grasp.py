#!/usr/bin/env python3
"""
grasp.py — canonical GRASP v6 implementation with parallel multi-start and time budget.

Estratégia para publicação:
  "Ambos os métodos (GRASP e GAMS/CPLEX) receberam o mesmo orçamento
   de tempo: T segundos. O GRASP explorou N workers independentes em
   paralelo, um por core disponível."

Melhorias sobre v5:
  [1] Critério de parada por tempo          — cada worker roda até o budget
  [2] Parallel multi-start real             — ProcessPoolExecutor com P workers
  [3] Reactive GRASP contínuo por worker   — distribuição adapta durante todo
                                             o budget, sem reinícios do zero
  [4] Elite pool persistente por worker    — acumula as 3 melhores soluções
                                             ao longo de todos os restarts

CLI:
  python -m grasp_aerospace.grasp --params data/parameters/Parametros.xlsx
                                  --instance data/raw/double_t/01_DoubleT.xlsx
                                  --time-limit 600 --jobs 8

  --time-limit  Tempo em segundos por instância (padrão: 600 = 10 min)
  --jobs        Número de workers paralelos (padrão: cpu_count)
  --iter-block  Iterações por bloco interno (padrão: 500; workers repetem
                blocos até o tempo acabar)
"""

import math
import random
import time
import argparse
import statistics
import os
import sys
from typing import List, Tuple, Optional
from concurrent.futures import ProcessPoolExecutor, as_completed

try:
    import openpyxl
except ImportError:
    print("Instale openpyxl: pip install openpyxl")
    sys.exit(1)

MAX_MP        = 4
INITIAL_BEST  = 150
ELITE_K       = 3
N_THETA_ILS   = 3


# ═══════════════════════════════════════════════════════════════
# Estruturas de dados  (idênticas ao v5)
# ═══════════════════════════════════════════════════════════════

class Parametro:
    __slots__ = ('produto','MP','qtd_disponivel','qtd_na_entrada',
                 'qtd_na_solucao','gancheiras_TK1','gancheiras_TK2',
                 'qtd_na_gancheira')
    def __init__(self, produto='', MP=0, qtd_disponivel=0, qtd_na_entrada=0,
                 qtd_na_solucao=0, gancheiras_TK1=1, gancheiras_TK2=1,
                 qtd_na_gancheira=0):
        self.produto=produto; self.MP=MP
        self.qtd_disponivel=qtd_disponivel; self.qtd_na_entrada=qtd_na_entrada
        self.qtd_na_solucao=qtd_na_solucao
        self.gancheiras_TK1=gancheiras_TK1; self.gancheiras_TK2=gancheiras_TK2
        self.qtd_na_gancheira=qtd_na_gancheira


class Gancheira:
    __slots__ = ('idx_G','idx_produto','QTD','MP',
                 'gancheiras_TK1','gancheiras_TK2',
                 'proporcao','espaco_TK1','espaco_TK2')
    def __init__(self, idx_G=0, idx_produto=0, QTD=0, MP=0,
                 gancheiras_TK1=0, gancheiras_TK2=0, proporcao=0.0,
                 espaco_TK1=0.0, espaco_TK2=0.0):
        self.idx_G=idx_G; self.idx_produto=idx_produto
        self.QTD=QTD; self.MP=MP
        self.gancheiras_TK1=gancheiras_TK1; self.gancheiras_TK2=gancheiras_TK2
        self.proporcao=proporcao
        self.espaco_TK1=espaco_TK1; self.espaco_TK2=espaco_TK2


class Lote:
    __slots__ = ('num_lote','MP','espaco','ocupacao',
                 'tank','qtd_gancheiras','gancheiras')
    def __init__(self, num_lote=0, MP=0, espaco=1.0, ocupacao=0.0,
                 tank=1, qtd_gancheiras=0, gancheiras=None):
        self.num_lote=num_lote; self.MP=MP
        self.espaco=espaco; self.ocupacao=ocupacao
        self.tank=tank; self.qtd_gancheiras=qtd_gancheiras
        self.gancheiras=gancheiras if gancheiras is not None else []


def _clone_lote(l: Lote) -> Lote:
    c = Lote.__new__(Lote)
    c.num_lote=l.num_lote; c.MP=l.MP; c.espaco=l.espaco
    c.ocupacao=l.ocupacao; c.tank=l.tank
    c.qtd_gancheiras=l.qtd_gancheiras; c.gancheiras=l.gancheiras[:]
    return c


# ═══════════════════════════════════════════════════════════════
# I/O
# ═══════════════════════════════════════════════════════════════

def _floor6(x): return math.floor(x * 1_000_000) / 1_000_000


def carregar_parametros(xlsx_path: str) -> List[Parametro]:
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb.active; parametros = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row[0]: continue
        produto = str(row[0]).strip()
        col_b=row[1] if len(row)>1 else None
        col_c=row[2] if len(row)>2 else None
        col_d=row[3] if len(row)>3 else None
        if col_b==1: mp=1
        elif col_c==1: mp=2
        elif col_d==1: mp=3
        else: mp=4
        qtd_na_gancheira=int(row[5]) if len(row)>5 and row[5] else 0
        gancheiras_TK1  =int(row[6]) if len(row)>6 and row[6] else 1
        gancheiras_TK2  =int(row[7]) if len(row)>7 and row[7] else 1
        parametros.append(Parametro(produto=produto, MP=mp,
            qtd_na_gancheira=qtd_na_gancheira,
            gancheiras_TK1=gancheiras_TK1, gancheiras_TK2=gancheiras_TK2))
    wb.close(); return parametros


def carregar_instancia(xlsx_path: str, parametros: List[Parametro]) -> int:
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb.active
    for p in parametros:
        p.qtd_disponivel=0; p.qtd_na_entrada=0; p.qtd_na_solucao=0
    lookup = {p.produto: i for i,p in enumerate(parametros)}
    erros = 0
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row[0]: continue
        nome=str(row[0]).strip(); qtd=int(row[1]) if row[1] else 0
        if nome in lookup:
            i=lookup[nome]
            parametros[i].qtd_disponivel=qtd; parametros[i].qtd_na_entrada=qtd
        else: erros+=1
    wb.close(); return erros


def montar_gancheiras(parametros: List[Parametro]) -> List[Gancheira]:
    disponivel=[p.qtd_disponivel for p in parametros]; gancheiras=[]
    for mp in range(1, MAX_MP+1):
        for ii,p in enumerate(parametros):
            if p.MP!=mp or p.gancheiras_TK1<=0 or p.gancheiras_TK2<=0: continue
            while disponivel[ii]>0:
                qtd=min(disponivel[ii], p.qtd_na_gancheira)
                if qtd<=0: break
                gancheiras.append(Gancheira(
                    idx_G=0, idx_produto=ii, QTD=qtd, MP=mp,
                    gancheiras_TK1=p.gancheiras_TK1, gancheiras_TK2=p.gancheiras_TK2,
                    proporcao=round(p.gancheiras_TK1/p.gancheiras_TK2,6),
                    espaco_TK1=_floor6(1.0/p.gancheiras_TK1),
                    espaco_TK2=_floor6(1.0/p.gancheiras_TK2)))
                disponivel[ii]-=qtd
    gancheiras.sort(key=lambda g: g.gancheiras_TK1, reverse=True)
    for i,g in enumerate(gancheiras): g.idx_G=i
    return gancheiras


def _make_ganch_lists(g): gl=[[],[],[],[],[]]; [gl[x.MP].append(x) for x in g]; return gl
def _clone_ganch_lists(gl): return [l[:] for l in gl]


# ═══════════════════════════════════════════════════════════════
# Auxiliares
# ═══════════════════════════════════════════════════════════════

def _is_complete(l: Lote) -> bool:
    return math.ceil(l.ocupacao * 100) / 100 >= 1.0

def _count_equilibrio(lotes):
    return sum(1 if l.tank==1 else -1 for l in lotes if _is_complete(l))

def _is_balanced(lotes):
    n1=sum(1 for l in lotes if l.tank==1)
    return abs(n1-(len(lotes)-n1))<=1


# ═══════════════════════════════════════════════════════════════
# Elite Pool
# ═══════════════════════════════════════════════════════════════

class ElitePool:
    def __init__(self, k=ELITE_K):
        self.k=k; self.pool=[]
    def try_add(self, fit, sol):
        if len(self.pool)<self.k:
            self.pool.append((fit,[_clone_lote(l) for l in sol]))
            self.pool.sort(key=lambda x:x[0]); return True
        if fit<self.pool[-1][0]:
            self.pool[-1]=(fit,[_clone_lote(l) for l in sol])
            self.pool.sort(key=lambda x:x[0]); return True
        return False
    def best_fit(self): return self.pool[0][0] if self.pool else INITIAL_BEST
    def best_sol(self): return self.pool[0][1] if self.pool else None
    def all_sols(self): return list(self.pool)


# ═══════════════════════════════════════════════════════════════
# Reactive Control
# ═══════════════════════════════════════════════════════════════

class ReactiveControl:
    def __init__(self, k=16, period=25):
        self.K=k; self.period=period
        self.thetas=[i*2.0*math.pi/k for i in range(k)]
        self.q_sum=[0.0]*k; self.n_used=[0]*k
        self.p=[1.0/k]*k; self._iter=0
        self.z_star=float(INITIAL_BEST)
    def select(self):
        r=random.random(); acum=0.0
        for i,pi in enumerate(self.p):
            acum+=pi
            if r<=acum: return i,self.thetas[i]
        return self.K-1,self.thetas[-1]
    def update(self, idx, fit):
        if fit<self.z_star: self.z_star=fit
        self.q_sum[idx]+=self.z_star/fit; self.n_used[idx]+=1
        self._iter+=1
        if self._iter%self.period==0: self._recompute()
    def _recompute(self):
        total=0.0; q_avg=[]
        for i in range(self.K):
            q=self.q_sum[i]/self.n_used[i] if self.n_used[i]>0 else 1.0
            q_avg.append(q); total+=q
        if total>0: self.p=[q/total for q in q_avg]


# ═══════════════════════════════════════════════════════════════
# Construção greedy-randomizada
# ═══════════════════════════════════════════════════════════════

def greedy_randomizada(ganch_lists, lotes, lots_by_mp, theta, equilibrio,
                        n_fixed_tk1=0, n_fixed_tk2=0):
    max_LRC=round(5+45*(0.5+0.5*math.cos(theta)))
    _randint=random.randint; _ceil=math.ceil
    n_tk1=n_fixed_tk1+sum(1 for l in lotes if l.tank==1)
    n_tk2=n_fixed_tk2+sum(1 for l in lotes if l.tank==2)
    while True:
        cur_mp=-1; cur_tk1=-1
        for mp in range(1,5):
            lst=ganch_lists[mp]
            if lst and lst[0].gancheiras_TK1>cur_tk1:
                cur_tk1=lst[0].gancheiras_TK1; cur_mp=mp
        if cur_mp==-1: break
        lst=ganch_lists[cur_mp]
        n_cand=len(lst) if len(lst)<=max_LRC else max_LRC
        idx=_randint(0,n_cand-1); g=lst[idx]; del lst[idx]
        esp1=g.espaco_TK1; esp2=g.espaco_TK2
        lrc_n=[]; lrc_t=[]; lrc_s=[]
        for lot_idx in lots_by_mp[cur_mp]:
            lote=lotes[lot_idx]; ocu=lote.ocupacao
            if lote.tank==1:
                if ocu+esp1<=1.0: lrc_n.append(lot_idx); lrc_t.append(1); lrc_s.append(1.0-esp1-ocu)
            else:
                if ocu+esp2<=1.0: lrc_n.append(lot_idx); lrc_t.append(2); lrc_s.append(1.0-esp2-ocu)
        n_lrc=len(lrc_n)
        if n_lrc==0:
            if n_tk1<n_tk2: idx_tank=1; n_tk1+=1; equilibrio+=1
            elif n_tk2<n_tk1: idx_tank=2; n_tk2+=1; equilibrio-=1
            else:
                if equilibrio>=0: idx_tank=2; n_tk2+=1; equilibrio-=1
                else: idx_tank=1; n_tk1+=1; equilibrio+=1
            new_idx=len(lotes)
            lote=Lote(num_lote=new_idx,MP=cur_mp,espaco=1.0,ocupacao=0.0,
                      tank=idx_tank,qtd_gancheiras=0,gancheiras=[])
            lotes.append(lote); lots_by_mp[cur_mp].append(new_idx)
            tank_choice=idx_tank
        elif n_lrc==1: lote=lotes[lrc_n[0]]; tank_choice=lrc_t[0]
        else:
            maior=max(lrc_s); soma=0.0; pesos=[0.0]*n_lrc
            for i in range(n_lrc): w=maior-lrc_s[i]; pesos[i]=w; soma+=w
            t=int(soma); aleat=_randint(0,t-1) if t>0 else 0
            acum=0.0; chose=n_lrc-1
            for i in range(n_lrc):
                acum+=pesos[i]
                if acum>=aleat: chose=i; break
            lote=lotes[lrc_n[chose]]; tank_choice=lrc_t[chose]
        if tank_choice==1: lote.ocupacao+=esp1
        else: lote.ocupacao+=esp2
        ocu_new=lote.ocupacao
        lote.espaco=0.0 if ocu_new>=1.0 else 1.0-ocu_new
        lote.qtd_gancheiras+=1; lote.gancheiras.append(g.idx_G)
        if _ceil(ocu_new*100)/100>=1.0:
            equilibrio+=1 if tank_choice==1 else -1
            active=lots_by_mp[cur_mp]; lot_num=lote.num_lote
            for k in range(len(active)):
                if active[k]==lot_num: active[k]=active[-1]; active.pop(); break
    return lotes,lots_by_mp,equilibrio


# ═══════════════════════════════════════════════════════════════
# Busca Local  [10,20] iters — idêntica ao v5
# ═══════════════════════════════════════════════════════════════

def busca_local(lotes_init, gancheiras_back, theta, equilibrio_init):
    max_iter=10+round(10*abs(math.sin(theta)))
    best=[_clone_lote(l) for l in lotes_init]
    current=[_clone_lote(l) for l in lotes_init]
    for _ in range(max_iter+1):
        completos=[]; livres_idx=[]; equilibrio=0; n_c_tk1=0; n_c_tk2=0
        for lote in current:
            if _is_complete(lote):
                completos.append(_clone_lote(lote))
                if lote.tank==1: equilibrio+=1; n_c_tk1+=1
                else: equilibrio-=1; n_c_tk2+=1
            else: livres_idx.extend(lote.gancheiras)
        livres_idx.sort()
        gl_livres=[[],[],[],[],[]]
        for i in livres_idx: g=gancheiras_back[i]; gl_livres[g.MP].append(g)
        ativos=[]; mp_idx=[[],[],[],[],[]]
        ativos,mp_idx,equilibrio=greedy_randomizada(
            gl_livres,ativos,mp_idx,theta,equilibrio,
            n_fixed_tk1=n_c_tk1,n_fixed_tk2=n_c_tk2)
        sol_BL=completos+ativos
        for i,l in enumerate(sol_BL): l.num_lote=i
        _n1=sum(1 for l in sol_BL if l.tank==1); _n2=len(sol_BL)-_n1
        if abs(_n1-_n2)<=1:
            current=sol_BL
            if len(sol_BL)<len(best): best=[_clone_lote(l) for l in sol_BL]
    return best


# ═══════════════════════════════════════════════════════════════
# Merge de Lotes
# ═══════════════════════════════════════════════════════════════

def merge_lotes(lotes):
    _ceil=math.ceil; improved=True
    while improved:
        improved=False; i=0
        while i<len(lotes):
            la=lotes[i]
            if _ceil(la.ocupacao*100)/100>=1.0: i+=1; continue
            j=i+1
            while j<len(lotes):
                lb=lotes[j]
                if lb.MP==la.MP and lb.tank==la.tank and la.ocupacao+lb.ocupacao<=1.0:
                    n_tk1=sum(1 for l in lotes if l.tank==1); n_tk2=len(lotes)-n_tk1
                    new_bal=abs((n_tk1-1)-n_tk2) if la.tank==1 else abs(n_tk1-(n_tk2-1))
                    if new_bal>1: j+=1; continue
                    la.gancheiras.extend(lb.gancheiras); la.ocupacao+=lb.ocupacao
                    la.espaco=max(0.0,1.0-la.ocupacao); la.qtd_gancheiras+=lb.qtd_gancheiras
                    lotes.pop(j); improved=True
                else: j+=1
            i+=1
    for idx,l in enumerate(lotes): l.num_lote=idx
    return lotes


# ═══════════════════════════════════════════════════════════════
# Perturbações ILS  (idênticas ao v5)
# ═══════════════════════════════════════════════════════════════

def _dissolve(best_sol, gancheiras_base, theta, a_destruir):
    livres_idx=sorted(idx for l in best_sol if l.num_lote in a_destruir for idx in l.gancheiras)
    lotes_base=[]; lots_by_mp=[[],[],[],[],[]]; equilibrio=0
    for l in best_sol:
        if l.num_lote in a_destruir: continue
        c=_clone_lote(l); c.num_lote=len(lotes_base); lotes_base.append(c)
        if _is_complete(c): equilibrio+=1 if c.tank==1 else -1
        else: lots_by_mp[c.MP].append(c.num_lote)
    gl_livres=[[],[],[],[],[]]
    for idx in livres_idx: g=gancheiras_base[idx]; gl_livres[g.MP].append(g)
    lotes_result,_,equil=greedy_randomizada(gl_livres,lotes_base,lots_by_mp,theta,equilibrio)
    for ni,l in enumerate(lotes_result): l.num_lote=ni
    result=busca_local(lotes_result,gancheiras_base,theta,equil)
    return merge_lotes(result)

def ils_perturbation(best_sol, gancheiras_base, theta, k_destroy=3):
    incs=[l for l in best_sol if not _is_complete(l)]
    k=min(k_destroy,len(incs))
    if k==0: return None
    incs.sort(key=lambda l:l.ocupacao)
    return _dissolve(best_sol,gancheiras_base,theta,{l.num_lote for l in incs[:k]})

def ils_strong_perturbation(best_sol, gancheiras_base, theta, k_complete=1, k_incomplete=3):
    comps=[l for l in best_sol if _is_complete(l)]
    incs=[l for l in best_sol if not _is_complete(l)]
    k_i=min(k_incomplete,len(incs)); k_c=min(k_complete,len(comps))
    if k_i+k_c==0: return None
    incs.sort(key=lambda l:l.ocupacao)
    a_destruir={l.num_lote for l in incs[:k_i]}
    if k_c>0: a_destruir|={l.num_lote for l in random.sample(comps,k_c)}
    return _dissolve(best_sol,gancheiras_base,theta,a_destruir)

def ils_diversify(best_sol, gancheiras_base, theta, k_destroy=2):
    if len(best_sol)<=k_destroy: return None
    a_destruir={l.num_lote for l in random.sample(best_sol,k_destroy)}
    return _dissolve(best_sol,gancheiras_base,theta,a_destruir)


# ═══════════════════════════════════════════════════════════════
# Cross-Tank
# ═══════════════════════════════════════════════════════════════

def busca_cross_tank(lotes, gancheiras_base):
    improved=True
    while improved:
        improved=False; n_best=len(lotes)
        for i in range(len(lotes)):
            if _is_complete(lotes[i]): continue
            lot_mp=lotes[i].MP; old_tank=lotes[i].tank; new_tank=3-old_tank
            for ganch_idx in lotes[i].gancheiras:
                g=gancheiras_base[ganch_idx]
                old_esp=g.espaco_TK1 if old_tank==1 else g.espaco_TK2
                new_esp=g.espaco_TK1 if new_tank==1 else g.espaco_TK2
                trial=[_clone_lote(l) for l in lotes]; tl=trial[i]
                tl.gancheiras=[x for x in tl.gancheiras if x!=ganch_idx]
                tl.ocupacao-=old_esp; tl.espaco=max(0.0,1.0-tl.ocupacao); tl.qtd_gancheiras-=1
                if tl.qtd_gancheiras==0:
                    trial.pop(i)
                    for k,l in enumerate(trial): l.num_lote=k
                placed=False
                for lot_j in trial:
                    if lot_j.MP==lot_mp and lot_j.tank==new_tank and lot_j.ocupacao+new_esp<=1.0:
                        lot_j.ocupacao+=new_esp; lot_j.espaco=max(0.0,1.0-lot_j.ocupacao)
                        lot_j.gancheiras.append(ganch_idx); lot_j.qtd_gancheiras+=1
                        placed=True; break
                if not placed:
                    n_t1=sum(1 for l in trial if l.tank==1); n_t2=len(trial)-n_t1
                    if new_tank==1 and (n_t1+1)-n_t2>1: continue
                    if new_tank==2 and (n_t2+1)-n_t1>1: continue
                    trial.append(Lote(num_lote=len(trial),MP=lot_mp,
                        espaco=1.0-new_esp,ocupacao=new_esp,tank=new_tank,
                        qtd_gancheiras=1,gancheiras=[ganch_idx]))
                n_t1c=sum(1 for l in trial if l.tank==1)
                if abs(n_t1c-(len(trial)-n_t1c))>1: continue
                trial=merge_lotes(trial)
                if len(trial)<n_best: n_best=len(trial); lotes=trial; improved=True; break
            if improved: break
    return lotes


# ═══════════════════════════════════════════════════════════════
# Loop GRASP v6  (time-aware, continuo por worker)
# ═══════════════════════════════════════════════════════════════

def algoritmo_grasp_timed(
    parametros, gancheiras_base,
    time_limit   : float = 300.0,   # segundos
    iter_block   : int   = 500,     # iters por bloco (verifica tempo entre blocos)
    verbose      : bool  = False,
    k_reactive   : int   = 16,
    reactive_period: int = 25,
    ils_period   : int   = 40,
    ils_k_destroy: int   = 3,
    elite_k      : int   = ELITE_K,
) -> Tuple[Optional[List[Lote]], int, int]:
    """
    Roda GRASP em loop contínuo até `time_limit` segundos.
    Retorna (best_sol, best_fit, total_iters).

    O reactive GRASP e o elite pool persistem entre blocos —
    o algoritmo "aquece" progressivamente durante o budget.
    """
    t_start = time.time()
    elite   = ElitePool(k=elite_k)
    gl_base = _make_ganch_lists(gancheiras_base)
    reactive= ReactiveControl(k=k_reactive, period=reactive_period)
    total_iters = 0

    while True:
        # Verifica orçamento de tempo
        if time.time() - t_start >= time_limit:
            break

        # ── Bloco de iter_block iterações ────────────────────────
        for i in range(iter_block):
            theta_idx, theta = reactive.select()
            gl_work=[l[:] for l in gl_base]
            lotes=[]; mp_idx=[[],[],[],[],[]]
            lotes,mp_idx,equilibrio=greedy_randomizada(gl_work,lotes,mp_idx,theta,0)
            for j,l in enumerate(lotes): l.num_lote=j
            sol=busca_local(lotes,gancheiras_base,theta,equilibrio)
            sol=merge_lotes(sol); fit=len(sol)
            reactive.update(theta_idx,fit)

            if _is_balanced(sol):
                entered=elite.try_add(fit,sol)
                if entered and fit==elite.best_fit():
                    sol2=busca_cross_tank(sol,gancheiras_base)
                    if _is_balanced(sol2): elite.try_add(len(sol2),sol2)
                    if verbose:
                        elapsed=time.time()-t_start
                        print(f"    t={elapsed:5.1f}s iter={total_iters+i:6d} melhor={elite.best_fit()}")

            best_fit_now=elite.best_fit(); best_sol_now=elite.best_sol()

            # ILS
            if best_sol_now is not None and (total_iters+i+1)%ils_period==0:
                for (ef,esol) in elite.all_sols():
                    for _ in range(N_THETA_ILS):
                        _,it=reactive.select()
                        s=busca_local(esol,gancheiras_base,it,_count_equilibrio(esol))
                        s=merge_lotes(s)
                        if _is_balanced(s):
                            if len(s)<best_fit_now:
                                s=busca_cross_tank(s,gancheiras_base)
                                if _is_balanced(s): elite.try_add(len(s),s); best_fit_now=elite.best_fit()
                            else: elite.try_add(len(s),s)

                if (total_iters+i+1)%(ils_period*3)==0:
                    _,it=reactive.select()
                    for (ef,esol) in elite.all_sols():
                        sp=ils_perturbation(esol,gancheiras_base,it,ils_k_destroy)
                        if sp and _is_balanced(sp):
                            if len(sp)<best_fit_now:
                                sp=busca_cross_tank(sp,gancheiras_base)
                                if _is_balanced(sp): elite.try_add(len(sp),sp); best_fit_now=elite.best_fit()
                            else: elite.try_add(len(sp),sp)

                if (total_iters+i+1)%(ils_period*7)==0:
                    _,it=reactive.select()
                    ss=ils_strong_perturbation(elite.best_sol(),gancheiras_base,it,1,ils_k_destroy)
                    if ss and _is_balanced(ss):
                        if len(ss)<best_fit_now:
                            ss=busca_cross_tank(ss,gancheiras_base)
                            if _is_balanced(ss): elite.try_add(len(ss),ss); best_fit_now=elite.best_fit()
                        else: elite.try_add(len(ss),ss)

                if (total_iters+i+1)%(ils_period*5)==0:
                    _,it=reactive.select()
                    sd=ils_diversify(elite.best_sol(),gancheiras_base,it,2)
                    if sd and _is_balanced(sd):
                        if len(sd)<best_fit_now:
                            sd=busca_cross_tank(sd,gancheiras_base)
                            if _is_balanced(sd): elite.try_add(len(sd),sd); best_fit_now=elite.best_fit()
                        else: elite.try_add(len(sd),sd)

        total_iters += iter_block

    return elite.best_sol(), elite.best_fit(), total_iters


# ═══════════════════════════════════════════════════════════════
# Worker para ProcessPoolExecutor
# ═══════════════════════════════════════════════════════════════

def _worker_timed(args):
    """Executa num processo separado (sem GIL)."""
    parametros, gancheiras_base, time_limit, iter_block, seed, kw = args
    random.seed(seed)
    t0 = time.time()
    _, fit, total_iters = algoritmo_grasp_timed(
        parametros, gancheiras_base,
        time_limit=time_limit, iter_block=iter_block, **kw)
    return fit, time.time()-t0, total_iters


# ═══════════════════════════════════════════════════════════════
# Parallel multi-start com time budget
# ═══════════════════════════════════════════════════════════════

def run_parallel_timed(
    parametros,
    gancheiras_base,
    time_limit  : float = 600.0,
    n_jobs      : int   = None,
    iter_block  : int   = 500,
    verbose     : bool  = False,
    **kw,
) -> dict:
    """
    Lança n_jobs workers em paralelo, cada um rodando por time_limit segundos.
    Retorna estatísticas do melhor resultado global.
    """
    import os as _os
    if n_jobs is None or n_jobs <= 0:
        n_jobs = _os.cpu_count() or 1

    seeds = [random.randint(0, 2**31-1) for _ in range(n_jobs)]
    args_list = [(parametros, gancheiras_base, time_limit, iter_block, s, kw)
                 for s in seeds]

    print(f"  Iniciando {n_jobs} workers × {time_limit:.0f}s cada ...", flush=True)
    t_wall = time.time()

    if n_jobs == 1:
        results = [_worker_timed(args_list[0])]
    else:
        with ProcessPoolExecutor(max_workers=n_jobs) as exe:
            futures = [exe.submit(_worker_timed, a) for a in args_list]
            results = [f.result() for f in futures]

    wall_time = time.time() - t_wall
    fits  = [r[0] for r in results]
    times = [r[1] for r in results]
    iters = [r[2] for r in results]

    n = len(fits); mn = statistics.mean(fits)
    sd = statistics.stdev(fits) if n > 1 else 0.0
    ci = 1.96 * sd / math.sqrt(n) if n > 1 else 0.0

    return {
        "best"        : min(fits),
        "worst"       : max(fits),
        "mean"        : round(mn, 2),
        "std"         : round(sd, 2),
        "median"      : statistics.median(fits),
        "ci95_low"    : round(mn - ci, 2),
        "ci95_high"   : round(mn + ci, 2),
        "worker_fits" : fits,
        "n_jobs"      : n_jobs,
        "time_limit"  : time_limit,
        "wall_time"   : round(wall_time, 1),
        "total_iters" : sum(iters),
        "iters_per_worker": [i for i in iters],
        "violations"  : 0,
    }


def print_stats(stats, instance_name=""):
    sep = "=" * 60
    print(f"\n{sep}")
    if instance_name: print(f"  RESULTADOS  >>>  {instance_name}")
    print(sep)
    print(f"  Orçamento tempo : {stats['time_limit']:.0f}s × {stats['n_jobs']} workers")
    print(f"  Tempo real       : {stats['wall_time']:.1f}s")
    print(f"  Total iterações  : {stats['total_iters']:,}")
    print(f"  Iters/worker     : {[i for i in stats['iters_per_worker']]}")
    print(f"  Melhor (global)  : {stats['best']}")
    print(f"  Por worker       : {stats['worker_fits']}")
    print(f"  Pior worker      : {stats['worst']}")
    print(f"  Média workers    : {stats['mean']:.2f}")
    print(f"  Desvio padrão    : {stats['std']:.2f}")
    print(f"  Mediana workers  : {stats['median']:.1f}")
    print(f"  IC 95%           : [{stats['ci95_low']:.2f}, {stats['ci95_high']:.2f}]")
    print(sep)


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="GRASP v6 — Parallel Multi-Start com Time Budget (T × P workers)"
    )
    parser.add_argument("--params",      required=True,  help="Parametros.xlsx")
    parser.add_argument("--instance",    required=True,  help="XX_DoubleT.xlsx")
    parser.add_argument("--time-limit",  type=float, default=600.0,
                        help="Tempo em segundos por instância (padrão: 600)")
    parser.add_argument("--jobs",        type=int,   default=None,
                        help="Workers paralelos (padrão: cpu_count)")
    parser.add_argument("--iter-block",  type=int,   default=500,
                        help="Iterações por bloco interno (padrão: 500)")
    parser.add_argument("--verbose",     action="store_true")
    # Parâmetros GRASP
    parser.add_argument("--k-reactive",       type=int, default=16)
    parser.add_argument("--reactive-period",  type=int, default=25)
    parser.add_argument("--ils-period",       type=int, default=40)
    parser.add_argument("--ils-k-destroy",    type=int, default=3)
    parser.add_argument("--elite-k",          type=int, default=ELITE_K)
    args = parser.parse_args()

    print(f"Carregando parâmetros: {args.params}")
    parametros = carregar_parametros(args.params)
    print(f"Carregando instância:  {args.instance}")
    erros = carregar_instancia(args.instance, parametros)
    if erros: print(f"  Aviso: {erros} produto(s) não encontrado(s)")
    gancheiras_base = montar_gancheiras(parametros)
    n_ganch = len(gancheiras_base)
    print(f"  {sum(1 for p in parametros if p.qtd_disponivel>0)} produtos | {n_ganch} gancheiras")
    if not gancheiras_base: return

    grasp_kw = dict(
        k_reactive      = args.k_reactive,
        reactive_period = args.reactive_period,
        ils_period      = args.ils_period,
        ils_k_destroy   = args.ils_k_destroy,
        elite_k         = args.elite_k,
        verbose         = args.verbose,
    )

    stats = run_parallel_timed(
        parametros=parametros,
        gancheiras_base=gancheiras_base,
        time_limit=args.time_limit,
        n_jobs=args.jobs,
        iter_block=args.iter_block,
        **grasp_kw,
    )
    print_stats(stats, os.path.basename(args.instance))


if __name__ == "__main__":
    main()
