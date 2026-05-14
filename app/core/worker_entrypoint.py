"""Executable ARQ worker entrypoint for containerized deployments."""

from __future__ import annotations

from arq.worker import run_worker

from app.core.scheduler import get_worker_settings


def main() -> None:
    """Start the ARQ worker with lazily resolved application settings."""
    run_worker(get_worker_settings())


if __name__ == "__main__":
    main()
