# ReOrch Public Reliability Packs

These packs convert public manufacturing datasets into isolated, auditable
inputs for ReOrch reliability monitoring. Each pack keeps the publisher files,
canonical tables, injected incidents, provenance, checksums, and quality report
separate.

## Packs

| Pack | Tier | Source class | Current status |
| --- | --- | --- | --- |
| `p0_ulster_mes` | P0 | Real anonymized MES extract | Acquisition blocked at source |
| `p0_textile_schedule` | P0 | Real company schedule | Complete |
| `p1_flexible_packaging` | P1 | Public research scheduling data | Complete; factory origin unverified |
| `p1_aerospace_surface_treatment` | P1 | Real demand plus simulated stress | Complete |
| `p1_tablets_manufacturing` | P1 | Real anonymized planning data | Complete |

## Build and monitor

```bash
python tools/build_public_reliability_packs.py --pack all
python tools/run_public_reliability_packs.py --allow-blocked
python tools/run_public_reliability_packs.py
```

The first monitor command tolerates a source-acquisition outage while retaining
the failed pack in the report. The second command is strict and fails until all
official source files are present.

## Claim boundary

These packs are engineering evidence. They do not prove customer production
reliability, customer ROI, planner adoption, customer-specific constraint
coverage, or production writeback authorization.
