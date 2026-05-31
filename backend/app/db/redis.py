"""
db/redis.py — Redis connection management

WHY a connection pool for Redis?
  Same reason as PostgreSQL: opening a new TCP connection per request is
  expensive (~1ms overhead). A pool keeps connections warm and reuses them.

  redis-py manages a connection pool automatically when you create a client
  with from_url(). Every await client.get(...) borrows a connection from
  the pool, uses it, and returns it — no explicit checkout/checkin needed.

WHY hiredis?
  hiredis is a C extension that parses Redis protocol responses faster than
  pure Python. Installing redis[hiredis] gets you 10-20% better throughput
  for free. The API is identical — just faster under the hood.

  Interview question: "What is the Redis Serialization Protocol (RESP)?"
  RESP is the wire protocol Redis uses — a simple text-based protocol where
  each response starts with a type marker (+, -, :, $, *).
  hiredis parses this in C instead of Python.
"""

from typing import Optional
import redis.asyncio as aioredis

from app.core.config import settings

# Module-level singleton — one pool shared across all requests
# WHY module-level? The pool is expensive to create. Creating it once at
# import time means every request reuses the same connections.
_redis_client: Optional[aioredis.Redis] = None


async def get_redis() -> aioredis.Redis:
    """
    Return the shared Redis client (lazy initialization).

    WHY lazy init and not init at import time?
      At import time, the event loop may not exist yet (FastAPI creates it).
      Async clients must be created inside a running event loop.
      Lazy init on first call guarantees the loop exists.
    """
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,   # Return str instead of bytes — easier to work with
            max_connections=20,       # Pool size — tune based on expected concurrency
        )
    return _redis_client


async def close_redis() -> None:
    """Call on app shutdown to cleanly release all pool connections."""
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None


# ── FastAPI dependency ─────────────────────────────────────────────────────────
async def get_redis_dep() -> aioredis.Redis:
    """
    Dependency-injectable version of get_redis.

    Usage in any endpoint:
      async def my_endpoint(redis: Redis = Depends(get_redis_dep)):

    WHY not Depends(get_redis) directly?
      get_redis is an async function — FastAPI would call it and inject the
      coroutine, not the result. get_redis_dep awaits it properly.
      (In practice FastAPI handles async deps, but this is explicit.)
    """
    return await get_redis()
