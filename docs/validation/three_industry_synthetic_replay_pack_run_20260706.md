# Three-Industry Synthetic Replay Pack Evaluation

## Claim Boundary

This evaluates public-source-derived synthetic replay evidence. It can support BP technical validation, ROI proxy demonstration, and PoC pre-checks. It is not real customer production evidence, not customer ROI proof, and not solver replay unless baseline work order, operation, resource, and schedule tables are present.

## Summary

| Metric | Value |
| --- | ---: |
| Total incidents | 90 |
| Planner decisions | 90 |
| Execution feedback rows | 90 |
| Can run solver replay | False |

## Scenario Metrics

| Scenario | Evidence level | Incidents | Decisions | Feedback | Decision time saved min | Delay reduction min | Trial reduction | Audit complete | Secondary anomaly | Solver replay |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| CNC_AUTO_FJSP | synthetic_shadow_ready | 30 | 30 | 30 | 47.93 | 96.93 | 4.00 | 100.00% | 3.33% | False |
| SEMI_LED_FAB | synthetic_shadow_ready | 30 | 30 | 30 | 50.23 | 110.50 | 4.43 | 100.00% | 20.00% | False |
| PCBA_SMT_TEST | synthetic_shadow_ready | 30 | 30 | 30 | 53.77 | 112.93 | 3.73 | 100.00% | 10.00% | False |

## Required Next Tables For Solver Replay

- `work_orders`
- `operations`
- `resources`
- `current_schedule`
- `routing_precedence`
- `customer_constraint_tables_if_available`

## Safe External Wording

ReOrch has evaluated a public-source-derived synthetic-realistic three-industry replay pack covering CNC automotive FJSP, semiconductor/LED fab, and PCBA SMT/test repair scenarios. The pack supports evidence-structure, ROI-proxy, and PoC pre-check validation. It is not real customer production data, not customer ROI proof, and not production writeback evidence.
