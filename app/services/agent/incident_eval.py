"""Score the deterministic incident parser against a labelled case file.

The case file has two splits. ``dev`` cases were used while writing the
parser, so they only guard against regressions. ``holdout`` cases were written
afterwards and never tuned against; their score is the honest one.

An error is *unsafe* when the parser returns a confident wrong type. Falling
back to ``unknown`` is safe: the workflow then asks a person to confirm.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from app.core.paths import REPO_ROOT
from app.services.agent.incident_parsing import _parse_incident_text

DEFAULT_CASES = REPO_ROOT / "benchmark" / "agent_eval" / "incident_understanding.jsonl"


@dataclass
class SplitScore:
    total: int = 0
    exact: int = 0
    type_correct: int = 0
    resource_correct: int = 0
    duration_correct: int = 0
    unsafe_errors: list[str] = field(default_factory=list)
    misses: list[str] = field(default_factory=list)

    @property
    def exact_rate(self) -> float:
        return self.exact / self.total if self.total else 0.0


def load_cases(path: Path = DEFAULT_CASES) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def score(cases: list[dict]) -> dict[str, SplitScore]:
    scores: dict[str, SplitScore] = {}
    for case in cases:
        split = scores.setdefault(case["split"], SplitScore())
        parsed = _parse_incident_text(case["text"])
        type_ok = parsed.incident_type == case["type"]
        resource_ok = parsed.resource_id == case["resource"]
        duration_ok = parsed.estimated_duration_minutes == case["minutes"]
        split.total += 1
        split.type_correct += type_ok
        split.resource_correct += resource_ok
        split.duration_correct += duration_ok
        if type_ok and resource_ok and duration_ok:
            split.exact += 1
            continue
        split.misses.append(case["id"])
        if not type_ok and parsed.incident_type != "unknown":
            split.unsafe_errors.append(case["id"])
    return scores


def render(scores: dict[str, SplitScore]) -> str:
    lines = ["split      cases  exact  type  resource  duration  unsafe"]
    for name, item in sorted(scores.items()):
        lines.append(
            f"{name:<10} {item.total:>5}  {item.exact:>5}  {item.type_correct:>4}"
            f"  {item.resource_correct:>8}  {item.duration_correct:>8}  {len(item.unsafe_errors):>6}"
        )
        if item.misses:
            lines.append(f"           missed: {', '.join(item.misses)}")
    return "\n".join(lines)
