# -*- coding: utf-8 -*-
"""Gera Figuras 1-5 do artigo com dados CPLEX 22 + GRASP best-of-10. 300 dpi."""
import json, matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from collections import Counter

t=json.load(open('gamspy_full.json')); canon=json.load(open('canon_data.json'))
rep=json.load(open('/mnt/user-data/uploads/replicas_independentes.json'))
nb={k:min(r['best'] for r in rep[k]['runs'].values()) for k in rep}
N=[str(i) for i in range(1,31)]

def cell_lots(rec):
    if rec['complete'] and rec['lots'] and rec['lots']>0: return rec['lots']
    return None
def best_cplex(n,h):
    vs=[cell_lots(t[n][f'{s}_{h}']) for s in ('hard','soft')]
    vs=[v for v in vs if v is not None]
    return min(vs) if vs else None

plt.rcParams.update({'font.family':'serif','font.size':9,'axes.grid':True,
                     'grid.alpha':0.3,'figure.dpi':300})

# ---------- FIGURA 1: (a) GRASP vs LB ; (b) CPLEX-3h vs LB ----------
fig,(ax1,ax2)=plt.subplots(1,2,figsize=(8,3.6))
g=[nb[n] for n in N]; lb=[canon[n]['lb'] for n in N]; c3=[canon[n]['cplex_3H'] for n in N]
# (a) GRASP vs LB, colorido por delta
dlt=[gi-li for gi,li in zip(g,lb)]
cats=[0,1,2,3]; 
for ax,yv,xlab,ylab,title in [(ax1,g,'Lower bound (CPLEX dual bound)','GRASP solution','(a)'),
                               (ax2,c3,'Lower bound (CPLEX dual bound)','CPLEX best (3 h)','(b)')]:
    mn=min(min(lb),min(yv))-2; mx=max(max(lb),max(yv))+2
    ax.plot([mn,mx],[mn,mx],'k--',lw=0.8,zorder=1)
    ax.scatter(lb,yv,s=22,c='#d95f02',edgecolors='k',linewidths=0.3,zorder=2)
    ax.set_xlabel(xlab); ax.set_ylabel(ylab); ax.set_title(title,loc='left',fontsize=10)
    ax.set_xlim(mn,mx); ax.set_ylim(mn,mx); ax.set_aspect('equal')
plt.tight_layout(); plt.savefig('fig1.png',bbox_inches='tight'); plt.close()
print('fig1 ok')

# ---------- FIGURA 2: GRASP vs best-CPLEX scatter (a) 10min (b) 1h ----------
fig,(ax1,ax2)=plt.subplots(1,2,figsize=(8,3.6))
for ax,h,title in [(ax1,'10M','(a) 10 min'),(ax2,'1H','(b) 1 h')]:
    xs=[]; ys=[]
    for n in N:
        bc=best_cplex(n,h)
        if bc is None: continue
        xs.append(bc); ys.append(nb[n])
    mn=min(min(xs),min(ys))-2; mx=max(max(xs),max(ys))+2
    ax.plot([mn,mx],[mn,mx],'k--',lw=0.8,zorder=1)
    ax.scatter(xs,ys,s=22,c='#1b9e77',edgecolors='k',linewidths=0.3,zorder=2)
    ax.set_xlabel(f'CPLEX best ({title.split()[1]} {title.split()[2]})' if False else 'CPLEX best')
    ax.set_ylabel('GRASP'); ax.set_title(title,loc='left',fontsize=10)
    ax.set_xlim(mn,mx); ax.set_ylim(mn,mx); ax.set_aspect('equal')
plt.tight_layout(); plt.savefig('fig2.png',bbox_inches='tight'); plt.close()
print('fig2 ok')

# ---------- FIGURA 3: mean gap Δ=GRASP-CPLEX por estratégia (10min, 1h) ----------
import statistics
fig,ax=plt.subplots(figsize=(7,3.8))
strategies=[('Hard 10 min','hard','10M'),('Soft 10 min','soft','10M'),
            ('Hard 1 h','hard','1H'),('Soft 1 h','soft','1H')]
labels=[]; means=[]; ns=[]
for lab,s,h in strategies:
    diffs=[nb[n]-cell_lots(t[n][f'{s}_{h}']) for n in N if cell_lots(t[n][f'{s}_{h}']) is not None]
    labels.append(lab); means.append(statistics.mean(diffs)); ns.append(len(diffs))
colors=['#7570b3' if '10 min' in l else '#1b9e77' for l in labels]
bars=ax.bar(labels,means,color=colors,edgecolor='k',linewidth=0.4)
ax.axhline(0,color='k',lw=0.8)
ax.set_ylabel(r'Mean $\Delta$ lots (GRASP $-$ CPLEX)')
for b,m,n in zip(bars,means,ns):
    ax.text(b.get_x()+b.get_width()/2, m+(-0.25 if m<0 else 0.1),
            f'{m:+.2f}\n(n={n})',ha='center',va='top' if m<0 else 'bottom',fontsize=8)
ax.set_title('Negative = GRASP uses fewer lots',fontsize=9,loc='left')
plt.tight_layout(); plt.savefig('fig3.png',bbox_inches='tight'); plt.close()
print('fig3 ok')

# ---------- FIGURA 4: CPLEX outcomes (complete/insufficient/no) por estratégia ----------
def classify(rec):
    st=(rec.get('status') or '')
    if 'NoSolution' in st: return 'no'
    if rec.get('lots') is None: return 'no'
    if not rec['complete']: return 'ins' if rec['lots']>0 else 'no'
    return 'comp'
fig,ax=plt.subplots(figsize=(7,3.8))
cfg=[('Hard\n10 min','hard_10M'),('Soft\n10 min','soft_10M'),('Hard\n1 h','hard_1H'),('Soft\n1 h','soft_1H')]
comp=[]; ins=[]; no=[]
for lab,key in cfg:
    cl=[classify(t[n][key]) for n in N]
    comp.append(cl.count('comp')); ins.append(cl.count('ins')); no.append(cl.count('no'))
x=np.arange(len(cfg)); 
ax.bar(x,comp,label='Complete',color='#1b9e77',edgecolor='k',linewidth=0.4)
ax.bar(x,ins,bottom=comp,label='Insufficient',color='#d95f02',edgecolor='k',linewidth=0.4)
ax.bar(x,no,bottom=[c+i for c,i in zip(comp,ins)],label='No solution',color='#999999',edgecolor='k',linewidth=0.4)
ax.set_xticks(x); ax.set_xticklabels([c[0] for c in cfg]); ax.set_ylabel('# instances'); ax.set_ylim(0,32)
ax.legend(fontsize=8,loc='lower right'); ax.grid(axis='x')
plt.tight_layout(); plt.savefig('fig4.png',bbox_inches='tight'); plt.close()
print('fig4 ok')

# ---------- FIGURA 5: performance profiles (a) 10min (b) 1h ----------
fig,(ax1,ax2)=plt.subplots(1,2,figsize=(8,3.6))
def profile(ax,h,title):
    methods={'GRASP':{n:nb[n] for n in N}}
    methods['CPLEX Hard']={n:cell_lots(t[n][f'hard_{h}']) for n in N}
    methods['CPLEX Soft']={n:cell_lots(t[n][f'soft_{h}']) for n in N}
    # best por instância
    best={n:min([methods[m][n] for m in methods if methods[m][n] is not None],default=None) for n in N}
    taus=np.linspace(1,1.3,100)
    styles={'GRASP':'-','CPLEX Hard':'--','CPLEX Soft':':'}
    cols={'GRASP':'#1b9e77','CPLEX Hard':'#7570b3','CPLEX Soft':'#d95f02'}
    for m in methods:
        ratios=[methods[m][n]/best[n] for n in N if methods[m][n] is not None and best[n]]
        ys=[sum(1 for r in ratios if r<=tau)/30 for tau in taus]
        ax.plot(taus,ys,styles[m],color=cols[m],label=m,lw=1.4)
    ax.set_xlabel(r'Performance ratio $\tau$'); ax.set_ylabel('Fraction of instances')
    ax.set_title(title,loc='left',fontsize=10); ax.set_ylim(0,1.02); ax.legend(fontsize=8,loc='lower right')
profile(ax1,'10M','(a) 10 min'); profile(ax2,'1H','(b) 1 h')
plt.tight_layout(); plt.savefig('fig5.png',bbox_inches='tight'); plt.close()
print('fig5 ok')
