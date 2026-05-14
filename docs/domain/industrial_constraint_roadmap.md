# Industrial Constraint Roadmap

## Current PoC Coverage

The current PoC implements the core abnormal re-decision loop:

- Work orders.
- Operation precedence.
- Machine/resource assignment.
- Equipment anomaly intake.
- Current schedule snapshot.
- Impact analysis.
- Candidate plan generation.
- Recommendation matrix.
- Gantt difference view.
- Human confirmation.
- Writeback status tracking.
- Case/feedback persistence.

## Next-Stage Constraints

These constraints should be prioritized for real customer validation:

| Constraint | Why it matters | Data needed |
| --- | --- | --- |
| Changeover time | Prevents unrealistic machine swaps | Product family, process sequence, setup matrix |
| Material and batch availability | Prevents planning jobs before materials arrive | ERP/WMS/MES material status |
| Shift calendar | Prevents scheduling outside working time | Line/team calendar |
| Machine maintenance window | Prevents using unavailable equipment | MES/CMMS downtime and PM plan |
| Frozen zone | Protects near-term dispatch stability | APS/MES frozen horizon rules |
| Operator skill | Prevents assigning work without qualified staff | Skill matrix and shift roster |

## Advanced Constraints

Add after the customer data foundation is stable:

- Tooling and fixtures.
- Quality hold and rework.
- Multi-line synchronization.
- Supplier arrival uncertainty.
- Cross-workshop logistics time.
- Energy constraints.
- Carbon constraints.
- Sequence-dependent quality risk.

## Implementation Order

Recommended order:

```text
1. Calendar and maintenance windows
2. Frozen zone
3. Changeover time
4. Material/batch availability
5. Operator skill
6. Tooling/fixture constraints
7. Advanced quality/logistics/energy constraints
```

## Product Wording

Use this framing externally:

```text
The current PoC implements the core abnormal re-decision loop. Additional industrial constraints will be incorporated progressively according to customer data availability and scenario priority.
```
