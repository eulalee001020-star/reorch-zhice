# Constraint-to-Recovery Kernel Validation

## Purpose

This validation layer turns the technical story into testable system behavior:

```text
ScheduleSnapshot + Incident
-> Decision Graph
-> Recovery Operator Portfolio
-> Evidence Gates
```

It answers investor and customer due-diligence questions:

1. How does ReOrch locate the affected subgraph?
2. How does it choose repair methods instead of blindly globally rescheduling?
3. What stops a mathematically feasible but poorly evidenced plan from being recommended?
4. Why is the LLM not the scheduling authority?

## Implemented Scope

| Item | Implementation |
| --- | --- |
| Kernel models | `app/models/technical_kernel.py` |
| Kernel services | `app/services/technical_kernel.py` |
| API endpoints | `POST /api/v1/planning/technical-kernel/*` |
| Tests | `app/tests/test_technical_kernel.py` |
| Architecture doc | `docs/architecture/constraint_to_recovery_technical_stack.md` |

## Validated Behaviors

| Behavior | Test coverage |
| --- | --- |
| Decision graph builds work-order, operation, resource nodes and edges | `test_decision_graph_builds_affected_subgraph_and_frontier` |
| Equipment incident finds affected and downstream operations | `test_decision_graph_builds_affected_subgraph_and_frontier` |
| Frozen operations are excluded from the repairable frontier | `test_decision_graph_builds_affected_subgraph_and_frontier` |
| Alternative resources are found by required capabilities | `test_decision_graph_builds_affected_subgraph_and_frontier` |
| Equipment failures select wait, alternative-machine, local, and rolling repair operators | `test_recovery_operator_portfolio_selects_equipment_repair_paths` |
| Missing source refs downgrade formal explanation to reference-only | `test_evidence_gate_blocks_writeback_without_confirmation_and_source_refs` |
| Data blockers stop solving and recommendation | `test_evidence_gate_stops_solve_when_data_has_blockers` |
| API endpoints are callable | `test_technical_kernel_api` |

## Validation Command

```bash
pytest app/tests/test_technical_kernel.py -q
python -m ruff check app/models/technical_kernel.py app/services/technical_kernel.py app/api/planning.py app/tests/test_technical_kernel.py
```

Expected:

```text
5 passed
All checks passed
```

## Claim Boundary

The kernel currently covers the minimal system-engineering path for equipment
failure recovery. It is not yet a full industrial APS kernel for material,
quality, tooling, labor, outsourcing, and multi-site planning. Those domains
must be added as new graph node types, constraint types, recovery operators,
and quality gates before claiming full replacement.
