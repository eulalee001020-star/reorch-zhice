# Customer Recovery Evidence Pack

Use `customer_recovery_cases.template.json` as the schema example and provide
10 to 30 unique cases. Do not replace customer references with digital-twin or
manually invented identifiers.

The customer evidence gate requires, per case:

- incident and baseline schedule references;
- the planner's original baseline decision and confirmed provenance;
- baseline loss amount and currency;
- ReOrch plan reference;
- accept, adjust, or reject decision with planner and timestamp;
- MES/QMS execution event ids and actual loss amount.

Validate the pack with:

```bash
python tools/validate_customer_evidence_ledger.py \
  customer_recovery_cases.json \
  --output output/customer_recovery_evidence_ledger.json
```
