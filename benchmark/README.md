# ReOrch Benchmark Pack

This folder defines a reproducible data-contract and functional replay benchmark
for dynamic flexible job shop scheduling. It is not production-readiness evidence.

It is intentionally data-contract-first:

- `kpi_dictionary.json` defines KPI semantics and formulas.
- `constraint_dictionary.json` defines hard and soft constraints.
- `acceptance_criteria.json` defines release gates.
- `datasets/` contains reproducible scenario payloads.
- `import_templates/` contains ERP/MES/APS import templates.
- `scripts/run_benchmark.py` validates a dataset and computes baseline metrics.
- `../tools/run_large_fjsp_load_gate.py` runs the actual solver-backed replay and
  records input hash, p50/p95 latency, concurrency, solve coverage, and capacity
  rejection evidence.

The benchmark is designed to cover common dynamic scheduling events:

- equipment failure
- urgent order insertion
- due date change
- processing time drift
- material shortage
- quality rework

Synthetic or public benchmark results remain lab evidence. Production capacity
claims require customer-like 1k/5k/10k operation packs, multi-process load tests,
constraint coverage, HA/restore drills, and customer acceptance.
