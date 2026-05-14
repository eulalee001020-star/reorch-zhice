"""Pytest compatibility helpers."""

from __future__ import annotations

import asyncio
import inspect
import warnings

import pytest


@pytest.fixture(autouse=True)
def _legacy_event_loop_for_sync_tests(request):
    """Keep legacy sync tests using asyncio.get_event_loop() working on Python 3.13."""

    if inspect.iscoroutinefunction(request.function):
        yield
        return

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            asyncio.get_event_loop()
        created = False
        loop = None
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        created = True

    try:
        yield
    finally:
        if created and loop is not None:
            loop.close()
            asyncio.set_event_loop(None)
