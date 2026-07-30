"""Lightweight in-memory rate limiting (per IP, sliding window).
For multi-instance deployments swap this for a Redis backed limiter."""
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

_buckets: dict[str, deque] = defaultdict(deque)


def rate_limit(name: str, limit: int, window_seconds: int):
    def dependency(request: Request):
        ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (
            request.client.host if request.client else "unknown"
        )
        key = f"{name}:{ip}"
        now_ts = time.time()
        bucket = _buckets[key]
        while bucket and bucket[0] <= now_ts - window_seconds:
            bucket.popleft()
        if len(bucket) >= limit:
            raise HTTPException(
                status_code=429,
                detail="Too many requests. Please wait a moment and try again.",
            )
        bucket.append(now_ts)
    return dependency
