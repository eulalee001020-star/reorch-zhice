# NGS Learning-to-Rank Training Set

Tabular training data for the dispatch-ranking step of the NGS lab repair
workflow (see `docs/portfolio/ngs_lab_specialized_portfolio.md`). Each row is
one candidate task at one dispatch decision point in a simulated NGS
(next-generation sequencing) laboratory; the label is the rank the task
receives in a CP-SAT reference schedule.

This set was first released in February 2026 as the standalone repository
`ngs-scheduling-dataset` and is now maintained here.

## Shape

| Item | Value |
| --- | --- |
| File | `ngs_training_data.csv` |
| Rows | 554 |
| Feature columns | 28 |
| Label | `optimal_rank`, integer 1-42, lower is dispatched earlier |
| Missing values | none |
| Duplicate rows | none |

## Columns

| Group | Columns |
| --- | --- |
| Task (8) | `base_duration` (min), `remaining_ops`, `is_critical_path` (0/1), `reagent_type` (0-2), `job_priority` (1-5), `heuristic_rank`, `task_successor_outdegree`, `dynamic_slack` (min) |
| Machine (6) | `m_queue_len`, `m_backlog_time` (min), `m_setup_needed` (min), `m_utilization_1h`, `m_fail_rate_dynamic`, `m_versatility_score` |
| Staff and consumables (5) | `tech_available`, `oper_available`, `staff_util_rate`, `tips_inventory`, `reagent_stock` |
| Environment (9) | `sim_hour_of_day`, `system_load`, `batch_sync_gap`, `normalized_makespan_so_far`, `task_release_wait_time` (min), `successor_total_workload` (min), `job_completion_ratio`, `resource_bottleneck_prob`, `m_reliability_factor` |
| Label (1) | `optimal_rank` |

`heuristic_rank` is the rank given by the rule-based dispatcher at the same
decision point, so it doubles as the baseline to beat.

## Known limits

- **Synthetic.** Rows come from a simulator, not from a LIMS or a production
  lab. They support method comparison, not claims about any real laboratory.
- **Three constant columns.** `m_versatility_score` (0), `reagent_stock` (100)
  and `m_reliability_factor` (1) do not vary in this release and carry no
  signal. Drop them before training.
- **Small.** 554 rows is enough for a ranking baseline and for pipeline tests,
  not for a model you would trust out of distribution.
- **No group key.** Rows are not tagged with their decision point, so listwise
  ranking losses need the grouping to be reconstructed from `system_load` and
  `sim_hour_of_day`, or the task framed as pointwise regression.

## Load

```python
import csv
from pathlib import Path

path = Path("datasets/ngs_l2r_training/ngs_training_data.csv")
with path.open(newline="") as handle:
    rows = list(csv.DictReader(handle))
features = [name for name in rows[0] if name != "optimal_rank"]
```

`app/tests/test_ngs_l2r_dataset.py` pins the schema and the facts above, so a
changed file fails CI instead of silently shifting results.

## Licence

This directory is released for academic and educational use only, as in its
original release. It is not covered by the MIT licence that applies to the
rest of the repository.
