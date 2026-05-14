"""Redis-based sliding window rate limiter middleware.

Validates: Requirements 18.7
"""

from __future__ import annotations

import time
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from app.core.auth import CurrentUser, get_current_user
from app.core.redis_client import redis_client


class RateLimiter:
    """Sliding-window rate limiter backed by Redis sorted sets.

    Usage as a FastAPI dependency::

        limiter = RateLimiter(max_requests=60, window_seconds=60)

        @router.get("/items", dependencies=[Depends(limiter)])
        async def list_items(): ...
    """

    def __init__(
        self,
        max_requests: int = 60,
        window_seconds: int = 60,
    ) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds

    async def __call__(self, request: Request) -> None:
        """Check rate limit for the current request."""
        # Identify caller by API key or IP
        api_key = request.headers.get("X-API-Key")
        identifier = api_key or (request.client.host if request.client else "unknown")
        key = f"rate_limit:{request.url.path}:{identifier}"

        now = time.time()
        window_start = now - self.window_seconds

        pipe = redis_client.redis.pipeline()
        # Remove expired entries
        pipe.zremrangebyscore(key, 0, window_start)
        # Count remaining entries in window
        pipe.zcard(key)
        # Add current request
        pipe.zadd(key, {str(now): now})
        # Set key expiry to auto-cleanup
        pipe.expire(key, self.window_seconds)
        results = await pipe.execute()

        request_count: int = results[1]

        if request_count >= self.max_requests:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded: {self.max_requests} requests "
                f"per {self.window_seconds}s",
            )


# Pre-configured default limiter (60 req/min)
default_rate_limiter = RateLimiter(max_requests=60, window_seconds=60)
