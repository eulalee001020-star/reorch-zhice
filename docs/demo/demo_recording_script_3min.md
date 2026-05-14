# 3-Minute Executive Demo Script

## Audience

Plant manager, operations leader, business sponsor.

## Opening

```text
This demo shows how ReOrch supports abnormal-event re-decision. It does not
replace ERP, MES, or APS. It works above existing systems when a disruption
occurs, helps planners understand impact, compares recovery plans, and writes
back only after human confirmation.
```

## Timeline

### 0:00-0:30 - Context

Show the decision workbench.

```text
The factory is running a mixed schedule with shared CNC capacity. A critical
CNC cell, M-03, goes down for four hours. Several urgent orders now face
delivery risk.
```

### 0:30-1:05 - Incident And Impact

Show incident intake and impact analysis.

```text
The incident is structured into a standard event: machine down, affected
resource M-03, estimated duration four hours. The system identifies affected
operations and highlights which customer orders are at risk.
```

### 1:05-1:50 - Candidate Plans

Show Top-3 plans and matrix.

```text
ReOrch compares three recovery strategies: wait for repair, local repair, and
global reschedule. The recommended plan is local repair because the disruption
is concentrated on M-03 and alternative CNC capacity exists.
```

### 1:50-2:25 - Human Confirmation

Show confirmation panel.

```text
The planner remains in control. ReOrch recommends a plan, explains the tradeoff,
and the planner confirms before any writeback happens.
```

### 2:25-3:00 - Writeback And Learning

Show writeback status and case library.

```text
After confirmation, the system performs controlled sandbox writeback, records
the decision trail, and deposits the case for future reuse. In a real customer
site, we first run read-only integration, then shadow mode, then approved
writeback.
```

## Closing Line

```text
The value is faster response, lower delivery risk, less unnecessary schedule
disturbance, and a decision record that can be audited.
```
