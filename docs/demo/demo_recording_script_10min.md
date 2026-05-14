# 10-Minute Technical Review Demo Script

## Audience

Customer IT, digital manufacturing team, planning manager, MES/APS owner.

## Opening

```text
This is a representative sandbox demo. The data is fixed and validated against
the adapter-level contract. It demonstrates the full decision loop, while real
customer rollout still requires field mapping, read-only ingestion, shadow-mode
validation, and approved writeback.
```

## 0:00-1:00 - Architecture Boundary

Show or state:

```text
ReOrch does not replace ERP, MES, or APS. ERP remains the order source, MES
remains execution source, APS/MES remains schedule source. ReOrch is the
abnormal-event decision orchestration layer.
```

## 1:00-2:00 - Adapter Contract And Data Validation

Show `field_mapping_template.csv` and validation report.

```text
Different customers use different field names, so adapters map external fields
to a canonical data model. Before solving, the mapping validator checks required
fields, enum values, timestamps, references, and machine capabilities.
```

Mention:

```text
This sandbox dataset has 12 work orders, 48 operations, 8 machines, and 1 core
incident. The validation report has zero blocking errors.
```

## 2:00-3:00 - Incident Intake

Show natural-language incident input or the incident list.

```text
The M-03 failure is converted into a structured incident. AI is used for
understanding and structuring, but the solver and constraint checks are
deterministic tools.
```

## 3:00-4:20 - Impact Analysis

Show affected operations and orders.

```text
The system identifies operations scheduled on M-03 during the downtime window,
links them back to work orders, and estimates delivery risk. This is the first
decision gate: do we wait, locally repair, or globally reschedule?
```

## 4:20-5:50 - Candidate Plan Generation

Show plan comparison.

```text
The candidate plans represent different operational tradeoffs. Wait and repair
minimizes disturbance but risks urgent orders. Local repair moves only affected
CNC operations. Global reschedule may improve makespan but changes more of the
factory plan.
```

## 5:50-6:50 - Recommendation Logic

Show recommendation and explanation.

```text
The recommendation is not a free-form LLM decision. It is grounded in impact
scope, affected orders, downtime, slack, priority, alternative machine count,
and current load. AI explains the result in planner-friendly language.
```

## 6:50-7:50 - Human Confirmation

Show confirmation panel.

```text
The planner confirms, adjusts, or rejects. If the planner overrides, the system
captures the reason and structures it for future rule candidates.
```

## 7:50-8:50 - Controlled Writeback

Show writeback status.

```text
Writeback uses an idempotency key and is only triggered after confirmation.
Duplicate writeback should not apply changes twice. Partial failure is recorded
instruction by instruction and goes into retry or manual review.
```

## 8:50-9:30 - Audit And Case Library

Show decision record/case library.

```text
The system stores the incident, impact summary, candidates, recommendation,
confirmation, writeback status, and outcome. The current case library supports
persistence and decision memory; the product roadmap upgrades it to structured
similarity, outcome ranking, and vector retrieval.
```

## 9:30-10:00 - Real Customer Rollout

Close with the integration plan:

```text
The next step with customer systems is to request sample data or sandbox API
access, complete field mapping, run read-only ingestion, compare shadow-mode
recommendations against planner decisions, and only then enable human-approved
writeback in staging.
```
