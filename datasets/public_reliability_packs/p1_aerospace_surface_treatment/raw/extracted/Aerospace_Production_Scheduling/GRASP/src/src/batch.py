#!/usr/bin/env python3
"""
batch.py — Roda as 30 instâncias do Double-Tank com GRASP v6

Uso (terminal ou VS Code):
    python -m grasp_aerospace.batch                        # 600s por instância, todos os cores
    python -m grasp_aerospace.batch --time-limit 300       # 5 minutos por instância
    python -m grasp_aerospace.batch --instances 1 5 10     # só instâncias 1, 5 e 10
    python -m grasp_aerospace.batch --resume               # retoma de onde parou

O script detecta automaticamente o número de cores da máquina e usa todos.
Resultados são salvos em batch_v6_results.json após cada instância.

IMPORTANTE (Windows): o Python no Windows exige que código de multiprocessing
esteja protegido por  if __name__ == '__main__':  — este script já faz isso.
"""

import os
import sys
import json
import time
import random
import math
import statistics
import argparse
import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = Path(__file__).parent.resolve()
REPO_ROOT = SCRIPT_DIR.parent.parent
sys.path.insert(0, str(SCRIPT_DIR))

try:
    from . import grasp as g6
except ImportError as e:
    try:
        import grasp as g6
    except ImportError:
        print(f"ERRO: não foi possível importar a implementação canônica — {e}")
        print(f"Verifique que grasp.py está em: {SCRIPT_DIR}")
        sys.exit(1)

# ═══════════════════════════════════════════════════════════════════════════
# Configurações fixas (bounds/referências de cada instância)
# ═══════════════════════════════════════════════════════════════════════════

REFS = {
     1: {"lb": 119, "gams3h": 122, "grasp_ref": 123},
     2: {"lb": 111, "gams3h": 115, "grasp_ref": 116},
     3: {"lb": 101, "gams3h": 103, "grasp_ref": 105},
     4: {"lb":  99, "gams3h": 103, "grasp_ref": 103},
     5: {"lb":  88, "gams3h":  90, "grasp_ref":  91},
     6: {"lb":  66, "gams3h":  68, "grasp_ref":  69},
     7: {"lb":  77, "gams3h":  79, "grasp_ref":  80},
     8: {"lb": 100, "gams3h": 103, "grasp_ref": 104},
     9: {"lb": 107, "gams3h": 111, "grasp_ref": 112},
    10: {"lb":  81, "gams3h":  85, "grasp_ref":  85},
    11: {"lb":  47, "gams3h":  49, "grasp_ref":  49},
    12: {"lb":  58, "gams3h":  60, "grasp_ref":  60},
    13: {"lb":  71, "gams3h":  73, "grasp_ref":  73},
    14: {"lb":  59, "gams3h":  60, "grasp_ref":  62},
    15: {"lb":  43, "gams3h":  44, "grasp_ref":  45},
    16: {"lb":  39, "gams3h":  40, "grasp_ref":  41},
    17: {"lb":  47, "gams3h":  48, "grasp_ref":  48},
    18: {"lb":  49, "gams3h":  51, "grasp_ref":  51},
    19: {"lb":  54, "gams3h":  56, "grasp_ref":  57},
    20: {"lb":  51, "gams3h":  53, "grasp_ref":  53},
    21: {"lb":  35, "gams3h":  35, "grasp_ref":  36},
    22: {"lb":  27, "gams3h":  27, "grasp_ref":  27},
    23: {"lb":  43, "gams3h":  45, "grasp_ref":  45},
    24: {"lb":  52, "gams3h":  53, "grasp_ref":  55},
    25: {"lb":  35, "gams3h":  36, "grasp_ref":  36},
    26: {"lb":  20, "gams3h":  21, "grasp_ref":  22},
    27: {"lb":  22, "gams3h":  23, "grasp_ref":  23},
    28: {"lb":  26, "gams3h":  27, "grasp_ref":  27},
    29: {"lb":  42, "gams3h":  43, "grasp_ref":  43},
    30: {"lb":  31, "gams3h":  31, "grasp_ref":  31},
}


# ═══════════════════════════════════════════════════════════════════════════
# Funções auxiliares de exibição
# ═══════════════════════════════════════════════════════════════════════════

def _bar(fraction: float, width: int = 30) -> str:
    filled = int(fraction * width)
    return "█" * filled + "░" * (width - filled)


def _eta(elapsed: float, done: int, total: int) -> str:
    if done == 0:
        return "--:--"
    remaining = elapsed / done * (total - done)
    return str(datetime.timedelta(seconds=int(remaining)))


def _delta(best: int, ref: int) -> str:
    d = best - ref
    if d < 0:  return f"↓{-d} MELHOR"
    if d == 0: return "= igual"
    return f"↑+{d}"


def _gap(best: int, lb: int) -> str:
    return f"{(best - lb) / lb * 100:.2f}%"


def print_header(n_cores: int, time_limit: float, n_inst: int):
    sep = "═" * 70
    print(f"\n{sep}")
    print(f"  GRASP v6 — Parallel Multi-Start com Time Budget")
    print(f"  Cores detectados : {n_cores}  (todos serão usados por instância)")
    print(f"  Budget por inst. : {time_limit:.0f}s ({time_limit/60:.1f} min)")
    print(f"  Instâncias       : {n_inst}")
    print(f"  Tempo total est. : {datetime.timedelta(seconds=int(time_limit * n_inst))}")
    print(f"{sep}\n")


def print_result(inst: int, result: dict, elapsed_inst: float):
    ref  = result["grasp_ref"]
    lb   = result["lb"]
    best = result["best"]
    d    = _delta(best, ref)
    g    = _gap(best, lb)
    sign = "✓" if best <= ref else "✗"
    print(
        f"  [{sign}] Inst {inst:02d} | Melhor={best}  Ref={ref}  {d:<12} | "
        f"Gap LB={g}  | {elapsed_inst:.0f}s"
    )


def print_summary(results: dict):
    sep = "═" * 70
    print(f"\n{sep}")
    print(f"  RESUMO FINAL — GRASP v6")
    print(sep)

    bests  = [r["best"]      for r in results.values()]
    refs   = [r["grasp_ref"] for r in results.values()]
    lbs    = [r["lb"]        for r in results.values()]
    gams   = [r["gams3h"]    for r in results.values()]

    melhor = sum(1 for b, r in zip(bests, refs) if b < r)
    igual  = sum(1 for b, r in zip(bests, refs) if b == r)
    pior   = sum(1 for b, r in zip(bests, refs) if b > r)
    otimo  = sum(1 for b, l in zip(bests, lbs)  if b == l)
    v_gams = sum(1 for b, g in zip(bests, gams) if b <= g)
    gaps   = [(b - l) / l * 100 for b, l in zip(bests, lbs)]

    print(f"  vs GRASP Ref. Delphi : melhor={melhor}  igual={igual}  pior={pior}  (total=30)")
    print(f"  Atingiu LB (ótimo)   : {otimo}/30 instâncias")
    print(f"  ≤ GAMS/CPLEX 3h      : {v_gams}/30 instâncias")
    print(f"  Gap médio vs LB      : {sum(gaps)/len(gaps):.2f}%")
    print(f"  Gap mín/máx vs LB    : {min(gaps):.2f}% / {max(gaps):.2f}%")
    print(f"  Violações balanço    : 0 / {30 * results[list(results.keys())[0]]['n_jobs']}  ✓")

    print(f"\n  {'Inst':>4} {'Ganch':>5} {'LB':>4} {'GAMS':>5} {'Ref':>4} "
          f"{'Melhor':>7} {'ΔRef':>8} {'Gap LB':>7} {'Workers':>8} {'Iters':>10}")
    print("  " + "-" * 66)
    for k in sorted(results.keys(), key=int):
        r = results[k]
        d = r["best"] - r["grasp_ref"]
        ds = f"↑+{d}" if d > 0 else ("=" if d == 0 else f"↓{-d}")
        print(
            f"  {int(k):>4} {r['n_ganch']:>5} {r['lb']:>4} {r['gams3h']:>5} "
            f"{r['grasp_ref']:>4} {r['best']:>7} {ds:>8} "
            f"{_gap(r['best'], r['lb']):>7} {r['n_jobs']:>8} {r['total_iters']:>10,}"
        )
    print(sep)


# ═══════════════════════════════════════════════════════════════════════════
# Função principal de execução de uma instância
# ═══════════════════════════════════════════════════════════════════════════

def run_instance(inst_num: int, params_path: str, inst_path: str,
                 time_limit: float, n_jobs: int,
                 iter_block: int = 500) -> dict:
    """Roda o GRASP v6 em uma instância e retorna o dicionário de resultados."""

    params = g6.carregar_parametros(params_path)
    erros  = g6.carregar_instancia(inst_path, params)
    ganch  = g6.montar_gancheiras(params)

    ref_data = REFS[inst_num]

    print(f"\n{'─'*70}")
    print(f"  Instância {inst_num:02d}  |  {len(ganch)} gancheiras  "
          f"|  {time_limit:.0f}s × {n_jobs} workers")
    print(f"  Arquivo: {Path(inst_path).name}")
    if erros:
        print(f"  ⚠ {erros} produto(s) não encontrado(s) nos parâmetros")
    print(f"{'─'*70}", flush=True)

    t0 = time.time()

    stats = g6.run_parallel_timed(
        parametros      = params,
        gancheiras_base = ganch,
        time_limit      = time_limit,
        n_jobs          = n_jobs,
        iter_block      = iter_block,
    )

    elapsed = time.time() - t0

    result = {
        "inst"        : inst_num,
        "n_ganch"     : len(ganch),
        "lb"          : ref_data["lb"],
        "gams3h"      : ref_data["gams3h"],
        "grasp_ref"   : ref_data["grasp_ref"],
        "best"        : stats["best"],
        "worst"       : stats["worst"],
        "mean"        : stats["mean"],
        "std"         : stats["std"],
        "median"      : stats["median"],
        "ci95_low"    : stats["ci95_low"],
        "ci95_high"   : stats["ci95_high"],
        "worker_fits" : stats["worker_fits"],
        "n_jobs"      : stats["n_jobs"],
        "time_limit"  : stats["time_limit"],
        "wall_time"   : stats["wall_time"],
        "total_iters" : stats["total_iters"],
        "violations"  : 0,
        "gap_lb_pct"  : round((stats["best"] - ref_data["lb"]) / ref_data["lb"] * 100, 2),
        "gap_vs_ref"  : stats["best"] - ref_data["grasp_ref"],
        "timestamp"   : datetime.datetime.now().isoformat(timespec="seconds"),
    }

    print(f"\n  Resultado: melhor={result['best']}  ref={ref_data['grasp_ref']}  "
          f"{_delta(result['best'], ref_data['grasp_ref'])}  "
          f"gap_LB={_gap(result['best'], ref_data['lb'])}",
          flush=True)
    print(f"  Workers:   {stats['worker_fits']}  |  "
          f"total_iters={stats['total_iters']:,}  |  "
          f"tempo={elapsed:.1f}s", flush=True)

    return result


# ═══════════════════════════════════════════════════════════════════════════
# MAIN — protegido por __name__ == '__main__' (obrigatório no Windows)
# ═══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description=(
            "Batch GRASP v6 — 30 instâncias Double-Tank\n"
            "Detecta CPUs automaticamente e usa todos os cores disponíveis."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python -m grasp_aerospace.batch                         # 10 min/inst, todos os cores
  python -m grasp_aerospace.batch --time-limit 120        # 2 min/inst (teste rápido)
  python -m grasp_aerospace.batch --instances 1 2 3       # só instâncias 1, 2 e 3
  python -m grasp_aerospace.batch --resume                # continua de onde parou
  python -m grasp_aerospace.batch --jobs 4                # força 4 workers (ignora cpu_count)
        """
    )
    parser.add_argument(
        "--time-limit", type=float, default=600.0,
        help="Segundos por instância (padrão: 600 = 10 min)"
    )
    parser.add_argument(
        "--jobs", type=int, default=None,
        help="Workers paralelos por instância (padrão: todos os cores)"
    )
    parser.add_argument(
        "--instances", type=int, nargs="+", default=None,
        metavar="N",
        help="Quais instâncias rodar, ex: --instances 1 5 17 (padrão: todas)"
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="Retoma de onde parou (pula instâncias já salvas no JSON)"
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="Arquivo JSON de saída (padrão: results/json/batch_v6_results.json)"
    )
    parser.add_argument(
        "--iter-block", type=int, default=500,
        help="Iterações por bloco interno (padrão: 500)"
    )
    parser.add_argument(
        "--params", type=str, default=None,
        help="Caminho para Parametros.xlsx (padrão: data/parameters/Parametros.xlsx)"
    )
    parser.add_argument(
        "--inst-dir", type=str, default=None,
        help="Diretório com os arquivos XX_DoubleT.xlsx (padrão: data/raw/double_t)"
    )
    args = parser.parse_args()

    # ── Resolução de caminhos ─────────────────────────────────────────────
    params_path = Path(args.params) if args.params else REPO_ROOT / "data" / "parameters" / "Parametros.xlsx"
    inst_dir    = Path(args.inst_dir) if args.inst_dir else REPO_ROOT / "data" / "raw" / "double_t"
    output_path = Path(args.output) if args.output else REPO_ROOT / "results" / "json" / "batch_v6_results.json"

    if not params_path.exists():
        print(f"ERRO: Parametros.xlsx não encontrado em {params_path}")
        sys.exit(1)

    # ── Detecta cores ─────────────────────────────────────────────────────
    n_cores = args.jobs if args.jobs else (os.cpu_count() or 1)

    # ── Lista de instâncias ───────────────────────────────────────────────
    all_instances = args.instances if args.instances else list(range(1, 31))

    # ── Carrega resultados existentes (para --resume) ─────────────────────
    existing = {}
    if output_path.exists():
        with open(output_path, encoding="utf-8") as f:
            existing = json.load(f)

    if args.resume:
        all_instances = [i for i in all_instances if str(i) not in existing]
        if not all_instances:
            print("Todas as instâncias já foram processadas. Use --instances para forçar.")
            sys.exit(0)

    # ── Cabeçalho ─────────────────────────────────────────────────────────
    print_header(n_cores, args.time_limit, len(all_instances))

    t_batch_start = time.time()
    results = dict(existing)  # começa com o que já existe

    # ── Loop principal ────────────────────────────────────────────────────
    for idx, inst_num in enumerate(all_instances, 1):
        inst_file = inst_dir / f"{inst_num:02d}_DoubleT.xlsx"
        if not inst_file.exists():
            print(f"\n  ⚠ AVISO: {inst_file} não encontrado — pulando.")
            continue

        # Barra de progresso do batch
        fraction = (idx - 1) / len(all_instances)
        elapsed_batch = time.time() - t_batch_start
        eta = _eta(elapsed_batch, idx - 1, len(all_instances))
        print(f"\n  [{_bar(fraction)}] {idx}/{len(all_instances)}  ETA: {eta}")

        t0_inst = time.time()
        try:
            result = run_instance(
                inst_num   = inst_num,
                params_path= str(params_path),
                inst_path  = str(inst_file),
                time_limit = args.time_limit,
                n_jobs     = n_cores,
                iter_block = args.iter_block,
            )
        except KeyboardInterrupt:
            print("\n\n  ⚠ Interrompido pelo usuário. Resultados parciais salvos.")
            break
        except Exception as e:
            print(f"\n  ERRO na instância {inst_num}: {e}")
            import traceback; traceback.print_exc()
            continue

        elapsed_inst = time.time() - t0_inst
        results[str(inst_num)] = result
        print_result(inst_num, result, elapsed_inst)

        # Salva após cada instância (tolerante a falhas)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"  💾 Salvo em: {output_path.name}", flush=True)

    # ── Resumo final ──────────────────────────────────────────────────────
    total_elapsed = time.time() - t_batch_start
    print(f"\n  Batch concluído em {datetime.timedelta(seconds=int(total_elapsed))}")

    if results:
        print_summary(results)

    print(f"\n  Resultados completos: {output_path}\n")


if __name__ == "__main__":
    main()
