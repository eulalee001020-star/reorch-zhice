"""Run the decision loop locally with no Postgres, Redis or Kafka.

    python tools/run_local_demo.py                      # machine failure
    python tools/run_local_demo.py --scenario material  # supplier delay
    python tools/run_local_demo.py --scenario all
    python tools/run_local_demo.py --serve              # keep the API up on :8000

With --serve the last scenario stays in memory, so `npm run dev` in frontend/
shows the same case in the workbench.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import httpx  # noqa: E402
import uvicorn  # noqa: E402

from app.main import app  # noqa: E402
from app.services.validation.local_demo import (  # noqa: E402
    reset_in_memory_state,
    walk,
    walk_material,
)

PLANNER_KEY = "planner-key-001"
SCENARIOS = {
    "equipment": ("设备故障：M-03 停机 4 小时", walk),
    "material": ("供应延期：轴承到货推迟到次日", walk_material),
}


async def _run(scenarios: list[str], serve: bool, host: str, port: int) -> int:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://local-demo",
        headers={"X-API-Key": PLANNER_KEY},
        timeout=300,
    ) as client:
        for name in scenarios:
            title, runner = SCENARIOS[name]
            reset_in_memory_state()
            result = await runner(client)
            print(f"\nReOrch 本地演示 · {title}\n")
            for line in result.lines():
                print("  " + line)
    if not serve:
        return 0
    print(f"\nAPI 已保留在 http://{host}:{port} ，演示账号 planner / planner123")
    print("另开一个终端运行: cd frontend && npm install && npm run dev")
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning"))
    await server.serve()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=[*SCENARIOS, "all"], default="equipment")
    parser.add_argument("--serve", action="store_true", help="keep the API running afterwards")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    scenarios = list(SCENARIOS) if args.scenario == "all" else [args.scenario]
    return asyncio.run(_run(scenarios, args.serve, args.host, args.port))


if __name__ == "__main__":
    raise SystemExit(main())
