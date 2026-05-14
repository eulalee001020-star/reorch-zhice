"""Reset generated demo runtime artifacts to a deterministic baseline."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from demo.scripts.seed_demo_data import (  # noqa: E402
    DEFAULT_REPORT_PATH,
    DEFAULT_RUNTIME_DIR,
    DEFAULT_SOURCE_DIR,
    seed_demo_data,
)

import asyncio  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--runtime-dir", type=Path, default=DEFAULT_RUNTIME_DIR)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH)
    args = parser.parse_args()

    if args.runtime_dir.exists():
        shutil.rmtree(args.runtime_dir)
    args.runtime_dir.mkdir(parents=True, exist_ok=True)
    return asyncio.run(
        seed_demo_data(
            source_dir=args.source_dir,
            runtime_dir=args.runtime_dir,
            report_path=args.report_path,
            api_base_url=None,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
