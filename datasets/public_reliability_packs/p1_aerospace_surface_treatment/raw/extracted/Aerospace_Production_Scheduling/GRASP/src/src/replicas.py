#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
replicas.py  —  Réplicas independentes do GRASP v6 para o artigo de lot-minimization.

O QUE FAZ
  Para cada instância (1..30) e cada semente-mestre s em {1..N_SEEDS}, executa UMA rodada
  completa do GRASP v6 com 16 workers (--jobs 16), registrando o 'best' (melhor-de-16) daquela
  rodada. Cada (instância, semente) é uma RÉPLICA INDEPENDENTE e REPRODUZÍVEL.

  Reprodutibilidade: chamamos random.seed(s) ANTES de run_parallel_timed(). Como essa função
  gera os seeds dos 16 workers via random.randint() a partir do estado global do random, fixar
  a semente-mestre torna toda a rodada determinística. NÃO modificamos grasp.py.

COMO RODAR (na máquina do artigo: Ryzen 7, 32 GB, Win11)
  1) Instale o pacote com `python -m pip install -e .`
  2) python -m grasp_aerospace.replicas
  Opcional:
     python -m grasp_aerospace.replicas --time-limit 180 --seeds 10 --jobs 16
     python -m grasp_aerospace.replicas --instances 1,14,26

  O script SALVA INCREMENTALMENTE em replicas_independentes.json após cada rodada.
  Se for interrompido, basta rodar de novo: ele PULA o que já foi feito e continua.

ATENÇÃO AO TEMPO
  300 rodadas (30 inst × 10 seeds) × time-limit. Com 180s ≈ 15h; com 600s ≈ 50h.
  Recomendado: faça PRIMEIRO o teste-piloto (--instances 1,14,26 --seeds 1) com --time-limit 180
  e confira no fim se os 'best' batem com batch_v6_results.json (o script faz essa checagem e avisa).
"""

import argparse, json, os, sys, time, random, statistics, math
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
REPO_ROOT = SCRIPT_DIR.parent.parent

try:
    from . import grasp as G
except Exception as e:
    try:
        import grasp as G
    except Exception:
        print("ERRO ao importar a implementação canônica do GRASP.")
        print("Detalhe:", e); sys.exit(1)

OUT_JSON = REPO_ROOT / "results" / "json" / "replicas_independentes.json"
DEFAULT_PARAMS = REPO_ROOT / "data" / "parameters" / "Parametros.xlsx"
DEFAULT_INST_DIR = REPO_ROOT / "data" / "raw" / "double_t"


def instance_file(inst_dir, i):
    """Nome do arquivo da instância i (1..30). Ajuste aqui se o seu padrão diferir."""
    return inst_dir / f"{i:02d}_DoubleT.xlsx"


def load_existing():
    if OUT_JSON.exists():
        try:
            with open(OUT_JSON, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            print(f"Aviso: {OUT_JSON} ilegível; começando do zero.")
    return {}


def save(results):
    tmp = OUT_JSON.with_suffix(OUT_JSON.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    os.replace(tmp, OUT_JSON)  # escrita atômica: não corrompe se interromper


def t_critical_95(n):
    """t de Student bicaudal 97.5% para n-1 g.l. (tabela pequena; fallback 1.96)."""
    table = {2:12.706,3:4.303,4:3.182,5:2.776,6:2.571,7:2.447,8:2.365,
             9:2.306,10:2.262,11:2.228,12:2.201,15:2.145,20:2.093,30:2.045}
    if n in table: return table[n]
    keys = sorted(table)
    for k in keys:
        if n <= k: return table[k]
    return 1.96


def compute_stats(vals):
    n = len(vals)
    mean = statistics.mean(vals)
    sd = statistics.stdev(vals) if n > 1 else 0.0
    med = statistics.median(vals)
    t = t_critical_95(n)
    half = t * sd / math.sqrt(n) if n > 1 else 0.0
    return {
        "best": min(vals), "worst": max(vals),
        "mean": round(mean, 3), "median": med, "std": round(sd, 4),
        "ci95_low": round(mean - half, 3), "ci95_high": round(mean + half, 3),
        "t_crit": t, "n": n,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--params", default=str(DEFAULT_PARAMS))
    ap.add_argument("--inst-dir", default=str(DEFAULT_INST_DIR))
    ap.add_argument("--time-limit", type=float, default=180.0,
                    help="segundos por rodada (padrão 180; o artigo usou 600 no batch)")
    ap.add_argument("--jobs", type=int, default=16, help="workers por rodada (padrão 16)")
    ap.add_argument("--iter-block", type=int, default=500)
    ap.add_argument("--seeds", type=int, default=10, help="nº de sementes-mestre por instância")
    ap.add_argument("--instances", default="1-30",
                    help="ex.: '1-30' ou '1,14,26' (para o teste-piloto)")
    args = ap.parse_args()
    inst_dir = Path(args.inst_dir)

    # parse de --instances
    insts = []
    for part in args.instances.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-"); insts += list(range(int(a), int(b) + 1))
        elif part:
            insts.append(int(part))
    seeds = list(range(1, args.seeds + 1))

    print(f"Parâmetros: {args.params}")
    print(f"Instâncias: {insts}")
    print(f"Sementes:   {seeds}")
    print(f"Config:     time_limit={args.time_limit:.0f}s, jobs={args.jobs}")
    total = len(insts) * len(seeds)
    print(f"Total de rodadas: {total}  (estimativa de tempo em série: "
          f"~{total*args.time_limit/3600:.1f} h)\n")

    parametros = G.carregar_parametros(args.params)

    results = load_existing()
    done_before = sum(len(v.get("runs", {})) for v in results.values())
    if done_before:
        print(f"Retomando: {done_before} rodada(s) já concluída(s) serão puladas.\n")

    count = 0
    for i in insts:
        key = str(i)
        fpath = instance_file(inst_dir, i)
        if not fpath.exists():
            print(f"[inst {i}] arquivo {fpath} não encontrado — PULANDO instância.")
            continue

        if key not in results:
            results[key] = {"inst": i, "instance_file": str(fpath),
                            "time_limit": args.time_limit, "n_jobs": args.jobs,
                            "runs": {}}

        for s in seeds:
            count += 1
            sk = str(s)
            if sk in results[key]["runs"]:
                continue  # já feito

            # (re)carrega a instância nos parâmetros e monta gancheiras
            G.carregar_instancia(str(fpath), parametros)
            gancheiras = G.montar_gancheiras(parametros)

            # REPRODUTIBILIDADE: semeia o estado global antes da rodada
            random.seed(s)
            t0 = time.time()
            stats = G.run_parallel_timed(
                parametros=parametros,
                gancheiras_base=gancheiras,
                time_limit=args.time_limit,
                n_jobs=args.jobs,
                iter_block=args.iter_block,
            )
            wall = time.time() - t0

            results[key]["runs"][sk] = {
                "seed": s,
                "best": stats["best"],
                "worker_fits": stats["worker_fits"],
                "wall_time": round(wall, 1),
            }
            save(results)  # incremental: seguro contra interrupção
            print(f"[{count}/{total}] inst {i:2d} seed {s:2d} -> best={stats['best']} "
                  f"(wall {wall:.0f}s)")

        # estatísticas parciais por instância (sobre as réplicas já feitas)
        vals = [r["best"] for r in results[key]["runs"].values()]
        if vals:
            results[key]["stats"] = compute_stats(vals)
            save(results)

    print("\nConcluído (ou parcial). Resultados em", OUT_JSON)
    print("Envie esse arquivo de volta para a análise.\n")

    # checagem opcional vs batch_v6_results.json, se presente
    batch_path = REPO_ROOT / "results" / "json" / "batch_v6_results.json"
    if batch_path.exists():
        with open(batch_path, encoding="utf-8") as f:
            batch = json.load(f)
        print("Checagem rápida vs batch_v6_results.json (best das réplicas vs best do batch):")
        for i in insts:
            k = str(i)
            if k in results and "stats" in results[k] and k in batch:
                rb = results[k]["stats"]["best"]; bb = batch[k]["best"]
                flag = "" if rb == bb else "  <-- DIVERGE"
                print(f"  inst {i:2d}: replicas_best={rb}  batch_best={bb}{flag}")


if __name__ == "__main__":
    main()
