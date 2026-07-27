#!/usr/bin/env python3
"""
validate.py — valida rigorosamente uma solução GRASP do problema Double-Tank.

Verifica:
  1. Cobertura: toda gancheira aparece em exatamente 1 lote
  2. Homogeneidade MP: todas as gancheiras de um lote têm o mesmo MP do lote
  3. Capacidade: ocupação recalculada do zero ≤ 1.0 (sem depender do .ocupacao armazenado)
  4. Consistência: .ocupacao armazenado bate com o recalculado (tolerância 1e-6)
  5. Equilíbrio: balanço TK1 vs TK2 em lotes completos (diferença ≤ 1)
  6. Quantidade total de itens: soma QTD das gancheiras == qtd_na_entrada

Uso:
    python -m grasp_aerospace.validate <params.xlsx> <instancia.xlsx> [--inst N] [--seed S] [--iter I] [--verbose]

Exemplo:
    python -m grasp_aerospace.validate data/parameters/Parametros.xlsx data/raw/double_t/21_DoubleT.xlsx --seed 314 --iter 500
"""

import sys, os, math, random, argparse

try:
    from .legacy import grasp_v4 as gv4
except ImportError:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "legacy"))
    import grasp_v4 as gv4

TOLAR = 1e-6   # tolerância de ponto flutuante para ocupação


def recalc_ocupacao(lote, gancheiras_base):
    """Recalcula ocupação a partir dos índices armazenados (não usa lote.ocupacao)."""
    total = 0.0
    for idx in lote.gancheiras:
        g = gancheiras_base[idx]
        total += g.espaco_TK1 if lote.tank == 1 else g.espaco_TK2
    return total


def validar(lotes, gancheiras_base, parametros, verbose=False):
    erros   = []
    avisos  = []
    n_ganch = len(gancheiras_base)

    # ── 1. Cobertura ────────────────────────────────────────────────────────
    contagem = [0] * n_ganch
    for lote in lotes:
        for idx in lote.gancheiras:
            if idx < 0 or idx >= n_ganch:
                erros.append(f"Lote {lote.num_lote}: índice de gancheira inválido {idx}")
            else:
                contagem[idx] += 1

    for idx, cnt in enumerate(contagem):
        if cnt == 0:
            g = gancheiras_base[idx]
            erros.append(f"Gancheira {idx} (produto {g.idx_produto}, MP{g.MP}) NAO PROGRAMADA")
        elif cnt > 1:
            erros.append(f"Gancheira {idx} aparece em {cnt} lotes (duplicata!)")

    # ── 2. Homogeneidade MP ─────────────────────────────────────────────────
    for lote in lotes:
        for idx in lote.gancheiras:
            g = gancheiras_base[idx]
            if g.MP != lote.MP:
                erros.append(f"Lote {lote.num_lote} (MP{lote.MP}): "
                             f"gancheira {idx} tem MP{g.MP}")

    # ── 3. Capacidade (recalculada) ─────────────────────────────────────────
    for lote in lotes:
        ocu_real = recalc_ocupacao(lote, gancheiras_base)
        if ocu_real > 1.0 + TOLAR:
            erros.append(f"Lote {lote.num_lote} (MP{lote.MP} TK{lote.tank}): "
                         f"ocupação recalculada={ocu_real:.6f} > 1.0  "
                         f"[{len(lote.gancheiras)} gancheiras]")

        # ── 4. Consistência ocupacao armazenado ────────────────────────────
        diff = abs(ocu_real - lote.ocupacao)
        if diff > TOLAR:
            avisos.append(f"Lote {lote.num_lote} (MP{lote.MP} TK{lote.tank}): "
                          f"ocupacao armazenada={lote.ocupacao:.6f} "
                          f"recalculada={ocu_real:.6f} diff={diff:.2e}")

    # ── 5. Equilíbrio TK1 vs TK2 ────────────────────────────────────────────
    # GAMS RESTRI_10/11: |Sum U[T,K1] - Sum U[T,K2]| <= 1 sobre TODOS os lotes ativos
    n_completos_tk1 = sum(1 for l in lotes
                          if math.ceil(l.ocupacao * 100) / 100 >= 1.0 and l.tank == 1)
    n_completos_tk2 = sum(1 for l in lotes
                          if math.ceil(l.ocupacao * 100) / 100 >= 1.0 and l.tank == 2)
    n_total_tk1 = sum(1 for l in lotes if l.tank == 1)
    n_total_tk2 = sum(1 for l in lotes if l.tank == 2)
    equilibrio_total = abs(n_total_tk1 - n_total_tk2)
    # Verificar balanço total (HARD constraint, equiv. a GAMS RESTRI_10/11)
    if equilibrio_total > 1:
        erros.append(f"Desequilíbrio TOTAL: TK1={n_total_tk1} TK2={n_total_tk2} "
                     f"|diff|={equilibrio_total}  (GAMS exige |diff|≤1)")

    # ── 6. Quantidade total de itens ─────────────────────────────────────────
    qtd_na_solucao = sum(gancheiras_base[idx].QTD
                         for lote in lotes for idx in lote.gancheiras)
    qtd_na_entrada = sum(p.qtd_na_entrada for p in parametros)
    if qtd_na_solucao != qtd_na_entrada:
        erros.append(f"Quantidade de itens: solução={qtd_na_solucao} "
                     f"entrada={qtd_na_entrada}  DIFEREM!")

    # ── Relatório ────────────────────────────────────────────────────────────
    n_lotes      = len(lotes)
    n_incompletos= sum(1 for l in lotes if math.ceil(l.ocupacao*100)/100 < 1.0)
    n_completos  = n_lotes - n_incompletos

    print(f"\n{'='*60}")
    print(f"  VALIDAÇÃO DA SOLUÇÃO")
    print(f"{'='*60}")
    print(f"  Total de lotes:      {n_lotes}  (TK1={n_total_tk1} TK2={n_total_tk2})")
    print(f"  Lotes completos:     {n_completos}  (TK1={n_completos_tk1} TK2={n_completos_tk2})")
    print(f"  Lotes incompletos:   {n_incompletos}")
    print(f"  Equilíbrio TOTAL:    |TK1-TK2|={equilibrio_total}  {'OK ✓' if equilibrio_total<=1 else 'VIOLADO ✗ (GAMS RESTRI_10/11)'}")
    print(f"  Itens na solução:    {qtd_na_solucao} / {qtd_na_entrada}")
    print(f"  Gancheiras cobertas: {sum(1 for c in contagem if c>0)} / {n_ganch}")

    if verbose:
        print(f"\n  Detalhe por lote:")
        print(f"  {'Lote':>5}  {'MP':>3}  {'Tank':>4}  {'Ganch':>5}  "
              f"{'Ocup_stored':>11}  {'Ocup_real':>10}  {'Status':>8}")
        for lote in sorted(lotes, key=lambda l: l.num_lote):
            ocu_r = recalc_ocupacao(lote, gancheiras_base)
            status = 'COMPLETO' if math.ceil(lote.ocupacao*100)/100 >= 1.0 else 'parcial'
            flag   = ' ***' if ocu_r > 1.0 + TOLAR else ''
            print(f"  {lote.num_lote:5d}  MP{lote.MP}  TK{lote.tank}  "
                  f"{len(lote.gancheiras):5d}  {lote.ocupacao:11.6f}  "
                  f"{ocu_r:10.6f}  {status}{flag}")

    print(f"\n  ERROS ({len(erros)}):")
    if erros:
        for e in erros: print(f"    [ERRO] {e}")
    else:
        print(f"    Nenhum — solução VIÁVEL ✓")

    if avisos:
        print(f"\n  AVISOS ({len(avisos)}):")
        for a in avisos: print(f"    [AVISO] {a}")

    ok = len(erros) == 0
    print(f"\n  STATUS: {'VIÁVEL' if ok else 'INVIÁVEL'}")
    print(f"{'='*60}\n")
    return ok, erros, avisos


def main():
    parser = argparse.ArgumentParser(description="Validador de solução GRASP Double-Tank")
    parser.add_argument('params',   help='Parametros.xlsx')
    parser.add_argument('instancia',help='XX_DoubleT.xlsx')
    parser.add_argument('--seed',   type=int, default=314)
    parser.add_argument('--iter',   type=int, default=600)
    parser.add_argument('--runs',   type=int, default=5,
                        help='Número de rodadas; valida a melhor')
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()

    p = gv4.carregar_parametros(args.params)
    gv4.carregar_instancia(args.instancia, p)
    g = gv4.montar_gancheiras(p)

    print(f"Instância: {args.instancia}  |  {len(g)} gancheiras  |  "
          f"{sum(px.qtd_na_entrada for px in p)} itens")

    melhor_sol  = None
    melhor_fit  = 999

    for run in range(args.runs):
        seed = args.seed + run
        random.seed(seed)
        sol, fit = gv4.algoritmo_grasp(p, g, n_iter=args.iter, verbose=False)
        print(f"  Rodada {run+1}/{args.runs}  seed={seed}  lotes={fit}")
        if fit < melhor_fit:
            melhor_fit = fit
            melhor_sol = sol

    print(f"\nMelhor solução encontrada: {melhor_fit} lotes")
    ok, erros, avisos = validar(melhor_sol, g, p, verbose=args.verbose)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
