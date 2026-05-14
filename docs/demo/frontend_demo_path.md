# Frontend Demo Path

## Primary Path

Use this path for the customer recording:

```text
Login
-> Decision Workbench
-> Incident intake or demo incident selection
-> Impact Analysis
-> Candidate Plans
-> Evaluation Matrix
-> Recommendation Explanation
-> Human Confirmation
-> Writeback Result
-> Case Library
```

## Screen Capture Checklist

Capture these screenshots during the dry run:

| Shot | Screen | Purpose |
| --- | --- | --- |
| 01 | Login | Show role-based user entry |
| 02 | Decision Workbench | Show abnormal-event operations cockpit |
| 03 | Incident intake | Show AI-assisted incident structuring |
| 04 | Impact analysis | Show affected orders and delivery risk |
| 05 | Plan comparison | Show Top-3 candidate plans |
| 06 | Gantt diff | Show what changed in the schedule |
| 07 | Recommendation | Show recommended plan and confidence |
| 08 | Confirmation | Show planner approval before writeback |
| 09 | Writeback status | Show controlled writeback result |
| 10 | Case library | Show decision/case deposition |

## Demo-Friendly Acceptance Criteria

- No loading state remains stuck.
- No raw traceback or stack detail appears.
- Button labels are understandable to non-engineering viewers.
- Recommendation text uses business terms: delay, disturbance, risk, feasibility.
- Writeback is visibly gated by planner confirmation.
- Case library is described as current persistence plus future hybrid retrieval.

## Non-Claim

Do not say the screenshots prove real customer integration. They prove the
sandbox end-to-end flow.
