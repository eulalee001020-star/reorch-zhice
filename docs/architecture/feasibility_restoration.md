# Feasibility Restoration

## Purpose

The restoration layer handles the case where dynamic rescheduling cannot return
an independently validated feasible schedule. It does not make an infeasible
model feasible by silently ignoring constraints. It identifies the failure type,
extracts bounded conflicts, simulates registered recovery actions, and only
returns an executable schedule after policy and approval gates pass.

## Runtime flow

```text
Requested solve
  -> feasible: independent validation and normal QualityGate
  -> UNKNOWN / timeout: preserve baseline and retry or expand search
  -> data or governance blocked: quarantine or wait for governed release
  -> proven INFEASIBLE:
       conflict refinement
       -> lexicographic minimum correction search
       -> pending what-if packs
       -> multi-role approval verification
       -> re-solve effective snapshot
       -> independent full validation
       -> feasibility certificate
```

The implementation is split into:

- `infeasibility_classifier.py`: separates timeout, proven infeasibility,
  governance failure, model failure, and capacity exhaustion.
- `constraint_assumption_registry.py`: versions hard and policy-gated constraint
  families and their allowed Recovery Operators.
- `constraint_conflict_refiner.py`: extracts source-state conflicts and proves
  contradictory release/duration/deadline or planning-freeze bounds.
- `feasibility_restoration.py`: searches the bounded Recovery Operator space and
  re-solves transformed effective snapshots.
- `recovery_approval_policy.py`: validates production approval signatures.
- `operational_constraint_validator.py`: independently rechecks every returned
  schedule.

## Failure classification

| Class | Meaning | Relaxation search |
|---|---|---|
| `feasible` | A validated incumbent exists | No |
| `search_exhausted` | Timeout or `UNKNOWN`; infeasibility is not proven | No |
| `capacity_exhausted` | Solver queue or process capacity unavailable | No |
| `model_invalid` | Invalid model/schema | No |
| `data_or_governance_blocked` | QMS, genealogy, source state, or validation gate blocks | No |
| `proven_infeasible` | CP-SAT or deterministic bounds prove contradiction | Yes |

`UNKNOWN` is never promoted to `INFEASIBLE`.

## Constraint boundary

The versioned registry marks safety, QMS release, quality holds, process
precedence, capability, schedule integrity, genealogy, source authority,
physical material availability, tooling, labor skills, transport, and buffer
capacity as constraints that must remain satisfied.

Recovery Operators may add an approved alternative, reduce governed demand, or
wait safely. They may not directly remove these hard constraints. Planning
freeze, explicitly relaxable operation deadlines, governed off-shift calendars,
and demand commitments are policy-gated rather than silently soft.

## Implemented Recovery Operators

| Operator | Tier | Effective-snapshot change | Gate |
|---|---:|---|---|
| Expand repair scope | L0 | Local to global repair scope | Automatic |
| Release planning freeze | L2 | Removes only a proven not-started planning freeze | Planner and management |
| Open overtime window | L3 | Removes an explicit `off_shift`, `relaxable` calendar block | Policy roles |
| Activate outsourcing | L3 | Activates a sourced vendor option with lead time and capacity | Policy roles |
| Activate substitute material | L3 | Activates a quantity-covering substitute row | Quality/engineering roles |
| Relax operation deadline | L4 | Removes only an explicitly `relaxable` boundary | Planner and management |
| Defer work order | L4 | Removes an unstarted order from active scope and records the exception | Management/customer service |
| Safe hold | L0 safety fallback | No production schedule is emitted | Always available |

Qualified alternative equipment, tooling, labor, transport, buffer, external
capacity, and material constraints remain modeled by the normal scheduler and
validator. Lot splitting and partial delivery are not inferred from order totals:
they require customer routing, batch-size, genealogy, quantity, and MES writeback
contracts before they can become executable Recovery Operators.

## Optimization order

Recovery action sets are searched in this lexicographic order:

1. lowest maximum intervention tier;
2. lowest deferred-order priority weight;
3. lowest customer-policy penalty cost;
4. fewest recovery actions;
5. normal schedule objective under the selected `goal_mode`.

This prevents a weighted score from trading quality or safety against delivery.
The first feasible set is marked optimal only when all lower-ranked registered
states were evaluated without an `UNKNOWN` result and the action space was not
truncated.

## Approval protocol

The endpoint is two-pass:

1. Call `POST /api/v1/runtime/feasibility-restoration/evaluate` without
   approvals. Feasible what-if packs have `status=pending_approval`, a preview
   schedule, no executable schedule, and no certificate.
2. Submit attestations for the selected deterministic action IDs. In staging and
   production, every attestation must be signed with
   `AUTH_RECOVERY_APPROVAL_SECRET` and match action ID, policy ID/version,
   approver role, approval time, expiry, and source reference.
3. The service applies only the approved actions, re-solves, and reruns the full
   validator. A certificate is issued only when hard violations equal zero.

Production also requires a `customer_owned=true` Recovery Policy. The system
default policy is limited to development and digital-twin rehearsal.

## Certificate and writeback

The certificate fingerprints the original snapshot, effective snapshot,
schedule, policy version, constraint-registry version, approved actions,
approval sources, deferred orders, and checked constraints.

A feasibility certificate always has `writeback_authorized=false`. It proves the
schedule passed the restoration gate; it does not replace planner confirmation,
second-person execution approval, a certified adapter, or the existing
`WritebackPolicy` permit.

## Large snapshots

Snapshots above `SOLVER_MAX_MODEL_OPERATIONS` use the existing bounded incident
subgraph decomposition. Subproblem failure classifications are propagated to the
restoration layer, including nested CP-SAT infeasibility and governance blockers.
Every merged schedule is validated globally against the effective snapshot.

## Claim boundary

Digital-twin tests prove deterministic software behavior. Customer policies,
real constraints, signed identities, historical incidents, planner decisions,
MES receipts, and realized cost coefficients remain customer acceptance evidence.
