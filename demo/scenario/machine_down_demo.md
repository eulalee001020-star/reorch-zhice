# Demo Scenario: M-03 Machine Down

## Factory Context

The factory is running a mixed discrete-manufacturing schedule with urgent
orders, normal orders, and shared CNC capacity. CNC Cell 03 (`M-03`) is a
critical resource but has alternatives (`M-02`, `M-04`) with limited remaining
capacity.

## Incident

```text
M-03 unexpectedly goes down at 2026-05-14 13:10 +08:00.
Maintenance estimates four hours of downtime.
Several urgent and high-priority orders now face delivery risk.
```

## Demo Goal

Show how ReOrch handles an abnormal event end to end:

```text
Incident intake
-> impact analysis
-> strategy selection
-> Top-3 candidate plans
-> recommendation explanation
-> planner confirmation
-> controlled mock writeback
-> audit trail
-> case library deposition
```

## Candidate Plan Story

| Plan | Strategy | Business interpretation |
| --- | --- | --- |
| Plan A | Wait and repair | Minimal schedule disturbance, but urgent orders risk delay |
| Plan B | Local repair | Reassign only affected M-03 operations to M-02/M-04 |
| Plan C | Global reschedule | Best makespan, but changes more operations and increases execution risk |

Recommended narration:

```text
The system recommends Local Repair because the impact is concentrated on M-03,
alternative CNC capacity exists, and urgent-order risk can be reduced without
changing the entire schedule.
```

## Customer-Safe Claim

This is a representative sandbox demo. It uses fixed data designed against the
adapter contract and validated by the mapping validator. It is not a claim that
ReOrch has already integrated with a specific customer's ERP/MES/APS.
