"""Run the decision loop locally with no Postgres, Redis or Kafka.

    python tools/run_local_demo.py            # walk the loop once and print it
    python tools/run_local_demo.py --serve    # then keep the API up on :8000

With --serve the seeded incident stays in memory, so `npm run dev` in
frontend/ shows the same case in the workbench.
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
from app.services.validation.local_demo import walk  # noqa: E402

PLANNER_KEY = "planner-key-001"


async def _run(serve: bool, host: str, port: int) -> int:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://local-demo",
        headers={"X-API-Key": PLANNER_KEY},
        timeout=300,
    ) as client:
        result = await walk(client)
    print("ReOrch 本地演示：异常 -> 影响 -> 候选 -> 推荐 -> 确认\n")
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
    parser.add_argument("--serve", action="store_true", help="keep the API running afterwards")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    return asyncio.run(_run(args.serve, args.host, args.port))


if __name__ == "__main__":
    raise SystemExit(main())
