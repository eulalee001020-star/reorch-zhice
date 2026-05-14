# ReOrch Benchmark Pack

This folder defines the first production-readiness benchmark for dynamic flexible job shop scheduling.

It is intentionally data-contract-first:

- `kpi_dictionary.json` defines KPI semantics and formulas.
- `constraint_dictionary.json` defines hard and soft constraints.
- `acceptance_criteria.json` defines release gates.
- `datasets/` contains reproducible scenario payloads.
- `import_templates/` contains ERP/MES/APS import templates.
- `scripts/run_benchmark.py` validates a dataset and computes baseline metrics.

The benchmark is designed to cover common dynamic scheduling events:

- equipment failure
- urgent order insertion
- due date change
- processing time drift
- material shortage
- quality rework

