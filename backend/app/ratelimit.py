"""Per-IP rate limiting (Phase 2.1).

Implemented as a FastAPI dependency over the `limits` library (the engine
slowapi wraps). A dependency — rather than slowapi's route decorator — is used
deliberately: the decorator rewrites the endpoint into a wrapper whose
`__globals__` don't contain our Pydantic models, which breaks FastAPI's
forward-ref resolution under `from __future__ import annotations`. A dependency
leaves the endpoint signature untouched.

Attach with `dependencies=[Depends(RateLimit(settings.rate_limit_login,
"login"))]` on the route. Disabled wholesale via `settings.rate_limit_enabled`
so the test suite isn't throttled.

Behind a reverse proxy, client IP comes from the proxy; configure it to set a
trustworthy `request.client.host` (or you rate-limit the proxy itself).
"""
# NB: no `from __future__ import annotations` here — FastAPI resolves this
# dependency's __call__ signature with no module globals (it's a class
# instance), so the `Request` annotation must be a real object, not a string.
from fastapi import HTTPException, Request
from limits import parse
from limits.storage import MemoryStorage
from limits.strategies import MovingWindowRateLimiter

from app.config import settings

# Process-local store (per worker). Fine at single-node scale; swap for
# RedisStorage to share limits across workers/nodes.
_storage = MemoryStorage()
_strategy = MovingWindowRateLimiter(_storage)


class RateLimit:
    """FastAPI dependency enforcing `limit_str` per client IP within `scope`.

    `scope` namespaces the counter so limits on different endpoints don't share
    a bucket (e.g. "login" vs "research").
    """

    def __init__(self, limit_str: str, scope: str) -> None:
        self._item = parse(limit_str)
        self._scope = scope

    def __call__(self, request: Request) -> None:
        if not settings.rate_limit_enabled:
            return
        ip = request.client.host if request.client else "unknown"
        if not _strategy.hit(self._item, self._scope, ip):
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded; please slow down and retry shortly.",
            )
