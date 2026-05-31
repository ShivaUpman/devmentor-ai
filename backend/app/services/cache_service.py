"""
services/cache_service.py — Caching, session storage, and token denylist

WHY is cache logic a service and not scattered across endpoints?
  Consistency. If caching logic is in each endpoint, 10 engineers write
  10 different TTL values for the same concept, 10 different key formats,
  and 10 different fallback strategies. One service = one canonical approach.

  This also makes it trivially mockable in tests — pass a fake CacheService
  and your endpoint tests never touch Redis.

Cache key design:
  Keys follow the pattern: {domain}:{identifier}[:{qualifier}]
  Examples:
    skill_assessment:abc123          — user abc123's full assessment
    interview_session:xyz789         — session xyz789's data
    rate_limit:192.168.1.1:1704067   — IP rate limit for minute 1704067

  WHY colons as separators?
    Redis namespace convention. Redis clients can display keys as a tree
    when grouped by colon-separated prefixes (like a filesystem).
    Also makes wildcard deletes easy: DEL skill_assessment:*

Interview question: "How do you handle cache invalidation?"
  The hardest problem in computer science (only half joking).
  Three strategies:
    TTL-based: data expires after N seconds — simple, eventual consistency
    Write-through: update cache on every write — consistent, two writes per update
    Event-based: invalidate on specific events (user updates profile → delete cache)
  We use TTL-based for skill assessments, event-based for sessions.
"""

import json
import uuid
from datetime import timedelta
from typing import Any, Optional

import redis.asyncio as aioredis

from app.core.config import settings


class CacheService:
    """
    Generic caching operations over Redis.

    All values are JSON-serialized — Redis stores strings, so we serialize
    Python dicts/lists to JSON strings on write and deserialize on read.
    """

    def __init__(self, redis: aioredis.Redis):
        self.redis = redis

    # ── Generic get/set/delete ─────────────────────────────────────────────────

    async def get(self, key: str) -> Optional[Any]:
        """
        Get a cached value. Returns None on cache miss.

        Cache hit: data found in Redis → return deserialized value
        Cache miss: key doesn't exist (never set, or TTL expired) → return None

        WHY TTL expiry is invisible to callers:
          Redis automatically deletes expired keys. Your code doesn't need to
          check "has this expired?" — a miss IS the expiry signal.
        """
        value = await self.redis.get(key)
        if value is None:
            return None
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            # If the stored value isn't valid JSON, treat as a miss and clean up
            await self.redis.delete(key)
            return None

    async def set(
        self,
        key: str,
        value: Any,
        ttl_seconds: int = 300,
    ) -> bool:
        """
        Cache a value with a TTL.

        WHY always set a TTL?
          A key without a TTL lives forever — until you manually delete it.
          Memory leak in disguise. Stale data with no eviction path.
          Rule: always set a TTL unless you're 100% certain you'll invalidate it explicitly.

        Args:
            key: Redis key
            value: Any JSON-serializable value
            ttl_seconds: Time-to-live. Default 300s (5 minutes).

        Returns:
            True if set successfully, False on error.
        """
        try:
            serialized = json.dumps(value, default=str)  # default=str handles UUIDs, datetimes
            await self.redis.setex(
                name=key,
                time=ttl_seconds,   # setex = SET with EXpiry — atomic
                value=serialized,
            )
            return True
        except Exception:
            # Cache writes are best-effort — failure is not fatal
            return False

    async def delete(self, key: str) -> int:
        """
        Delete a cached key immediately (cache invalidation).

        Returns: number of keys deleted (0 if key didn't exist)
        """
        return await self.redis.delete(key)

    async def delete_pattern(self, pattern: str) -> int:
        """
        Delete all keys matching a pattern.

        WHY use SCAN and not KEYS?
          KEYS pattern blocks Redis while scanning — blocks the entire server.
          At 10M keys, KEYS * could block for seconds, dropping all connections.
          SCAN iterates in batches — non-blocking, production-safe.

          Interview question: "Why is KEYS dangerous in production?"
          Answer: Redis is single-threaded. KEYS blocks all other commands
          while scanning. Use SCAN with a cursor for production-safe iteration.
        """
        deleted = 0
        cursor = 0
        while True:
            cursor, keys = await self.redis.scan(cursor=cursor, match=pattern, count=100)
            if keys:
                deleted += await self.redis.delete(*keys)
            if cursor == 0:
                break
        return deleted

    # ── Domain-specific cache helpers ──────────────────────────────────────────

    async def get_skill_assessments(self, user_id: uuid.UUID) -> Optional[list]:
        """
        Get cached skill assessments for a user.

        TTL choice: 5 minutes (300s).
        WHY 5 minutes and not 1 minute or 1 hour?
          Skill assessments change after each interview session (~10-30 min).
          5 minutes means at worst a slightly stale dashboard — acceptable UX.
          1 minute would be too many DB hits for a popular feature.
          1 hour could show very stale data if user just completed a session.
        """
        return await self.get(f"skill_assessment:{user_id}")

    async def set_skill_assessments(
        self, user_id: uuid.UUID, assessments: list
    ) -> bool:
        return await self.set(f"skill_assessment:{user_id}", assessments, ttl_seconds=300)

    async def invalidate_skill_assessments(self, user_id: uuid.UUID) -> int:
        """
        Called after a session completes — force fresh data on next request.

        This is event-based invalidation: we know exactly when assessments
        change (after a submission is scored), so we invalidate immediately
        rather than waiting for TTL expiry.
        """
        return await self.delete(f"skill_assessment:{user_id}")

    async def get_roadmap(self, user_id: uuid.UUID) -> Optional[list]:
        """
        Roadmaps are expensive to generate (ML inference).
        Cache for 1 hour — they change rarely.
        """
        return await self.get(f"roadmap:{user_id}")

    async def set_roadmap(self, user_id: uuid.UUID, roadmap: list) -> bool:
        return await self.set(f"roadmap:{user_id}", roadmap, ttl_seconds=3600)

    async def invalidate_roadmap(self, user_id: uuid.UUID) -> int:
        return await self.delete(f"roadmap:{user_id}")

    # ── Session / token management ──────────────────────────────────────────────

    async def store_refresh_token(
        self,
        user_id: uuid.UUID,
        token_hash: str,
    ) -> bool:
        """
        Store a hashed refresh token for true logout support.

        WHY store the HASH and not the token itself?
          If Redis is breached, attackers get token hashes, not tokens.
          On verification: hash the incoming token, compare to stored hash.

        WHY key = session:{user_id} and not session:{token_hash}?
          Keying by user_id lets us delete ALL sessions for a user (logout everywhere).
          DELETE session:{user_id} — one operation, all devices logged out.
          If we keyed by token, we'd need to track which tokens belong to which user.

        Real-world: for multi-device support, use a hash (Redis HSET):
          HSET session:{user_id} device_id token_hash
          This stores one entry per device. DEL session:{user_id} = logout all.
          HDEL session:{user_id} device_id = logout one device.
        """
        ttl = settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600
        return await self.set(f"session:{user_id}", token_hash, ttl_seconds=ttl)

    async def get_refresh_token_hash(self, user_id: uuid.UUID) -> Optional[str]:
        return await self.get(f"session:{user_id}")

    async def revoke_session(self, user_id: uuid.UUID) -> int:
        """
        Logout — invalidate all refresh tokens for this user.

        WHY this is "true" logout vs the stateless approach:
          Without this: a stolen refresh token works until it expires (7 days).
          With this: logout immediately invalidates the token — 0 second window.
        """
        return await self.delete(f"session:{user_id}")

    # ── Token denylist ─────────────────────────────────────────────────────────

    async def add_to_denylist(self, jti: str, ttl_seconds: int) -> bool:
        """
        Add a JWT ID to the denylist.

        On logout, the current access token's JTI is added here.
        On every authenticated request, check the denylist before accepting.

        WHY use the token's remaining lifetime as TTL?
          After the token would have expired anyway, the denylist entry is
          useless — no one can use an expired token. Automatic cleanup.

        Key: denylist:{jti}
        Value: "1" (just a flag — we only care about key existence)
        """
        return await self.set(f"denylist:{jti}", "1", ttl_seconds=ttl_seconds)

    async def is_denylisted(self, jti: str) -> bool:
        """Check if a token has been explicitly revoked."""
        value = await self.redis.get(f"denylist:{jti}")
        return value is not None

    # ── Leaderboard (Sorted Set example) ──────────────────────────────────────

    async def update_leaderboard(
        self,
        user_id: uuid.UUID,
        score: float,
    ) -> None:
        """
        Update the global leaderboard using a Redis Sorted Set.

        WHY Sorted Set and not a DB query?
          SELECT user_id, score FROM users ORDER BY score DESC LIMIT 10
          With indexes this is fine up to ~100k users.
          At 1M+ users: the sort dominates. Redis ZADD + ZREVRANGE is O(log N) always.

          Redis Sorted Set commands:
            ZADD leaderboard score member   — add/update score
            ZREVRANGE leaderboard 0 9       — top 10 (highest scores first)
            ZRANK leaderboard member        — rank of a specific user
            ZSCORE leaderboard member       — score of a specific user

          This is how Twitter's "trending topics" and game leaderboards work.

        Interview question: "How would you implement a real-time leaderboard?"
          Redis Sorted Set. O(log N) insert, O(log N + K) range query.
          Score = composite (e.g., total_score * 1e10 + timestamp for tie-breaking).
        """
        await self.redis.zadd("leaderboard:global", {str(user_id): score})
        # Keep only top 1000 — ZREMRANGEBYRANK removes lowest scores
        await self.redis.zremrangebyrank("leaderboard:global", 0, -1001)

    async def get_top_users(self, limit: int = 10) -> list[dict]:
        """Get top N users with their scores."""
        results = await self.redis.zrevrange(
            "leaderboard:global",
            0, limit - 1,
            withscores=True,
        )
        return [{"user_id": uid, "score": score} for uid, score in results]
