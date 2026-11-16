"""Print the incident-understanding score for the deterministic parser.

python tools/run_agent_eval.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.services.agent.incident_eval import load_cases, render, score  # noqa: E402


def main() -> int:
    scores = score(load_cases())
    print(render(scores))
    return 1 if any(item.unsafe_errors for item in scores.values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
