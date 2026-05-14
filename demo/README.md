# ReOrch Customer Demo Package

This package prepares a stable representative sandbox demo. It does not claim
real customer ERP/MES/APS integration.

## Scenario

```text
M-03 unexpectedly goes down for four hours.
Several high-priority work orders now face delivery risk.
ReOrch performs impact analysis, candidate plan generation, recommendation,
planner confirmation, controlled mock writeback, audit capture, and case
library deposition.
```

## Commands

```bash
make demo-reset
make demo-seed
make demo-seed-api
```

Generated runtime artifacts are written to:

```text
demo/runtime/
docs/demo/demo_validation_report.md
```

`make demo-seed-api` expects a running backend at:

```text
http://localhost:8000/api/v1
```

It posts the generated schedule snapshot and incident payload to the local API
so the frontend can run through the demo path.

## Positioning

Use this wording in customer meetings:

```text
This demo uses sandbox data designed against the adapter contract. Real
customer integration starts with field mapping and read-only validation,
then shadow-mode comparison, then human-approved writeback in staging.
```
