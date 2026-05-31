"""
tests/test_cache.py — Cache service tests

WHY mock Redis in unit tests?
  Real Redis tests are integration tests — they need a running server.
  Unit tests should be:
    - Fast (milliseconds, not seconds)
    - Isolated (no external dependencies)
    - Deterministic (same result every run)

  We mock the Redis client and test:
    1. Correct keys are constructed
    2. Correct TTLs are set
    3. JSON serialization/deserialization works
    4. Cache misses return None
    5. Errors are handled gracefully

Integration tests (not here) would use a real Redis — either a local
instance or testcontainers (Docker-in-Docker for tests).

Interview question: "What is the difference between unit tests and integration tests?"
  Unit: tests a single function/class in isolation, with mocked dependencies
  Integration: tests multiple components working together (e.g., FastAPI + Redis)
  E2E (end-to-end): tests the full user journey through the real system
"""

import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.cache_service import CacheService


@pytest.fixture
def mock_redis():
    """
    A mock Redis client.

    All Redis methods are mocked as AsyncMock (they're coroutines).
    We configure specific return values per test.
    """
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)    # Default: cache miss
    redis.setex = AsyncMock(return_value=True)
    redis.delete = AsyncMock(return_value=1)
    redis.scan = AsyncMock(return_value=(0, []))  # Empty scan by default
    redis.zadd = AsyncMock()
    redis.zrevrange = AsyncMock(return_value=[])
    redis.zremrangebyrank = AsyncMock()
    return redis


@pytest.fixture
def cache(mock_redis):
    return CacheService(mock_redis)


class TestCacheGetSet:
    @pytest.mark.asyncio
    async def test_cache_miss_returns_none(self, cache, mock_redis):
        mock_redis.get.return_value = None
        result = await cache.get("nonexistent:key")
        assert result is None

    @pytest.mark.asyncio
    async def test_cache_hit_returns_deserialized_value(self, cache, mock_redis):
        data = {"skill": "DSA", "score": 0.75}
        mock_redis.get.return_value = json.dumps(data)

        result = await cache.get("skill_assessment:abc")
        assert result == data

    @pytest.mark.asyncio
    async def test_set_uses_setex_with_ttl(self, cache, mock_redis):
        """setex atomically sets value AND expiry — verify we use it."""
        await cache.set("test:key", {"value": 42}, ttl_seconds=600)

        mock_redis.setex.assert_called_once()
        call_kwargs = mock_redis.setex.call_args
        # Verify TTL is passed
        assert call_kwargs.kwargs.get("time") == 600 or call_kwargs.args[1] == 600

    @pytest.mark.asyncio
    async def test_set_serializes_uuid(self, cache, mock_redis):
        """UUIDs must be serialized to strings — JSON can't handle UUID objects."""
        uid = uuid.uuid4()
        await cache.set("test:key", {"id": uid}, ttl_seconds=300)

        mock_redis.setex.assert_called_once()
        # Extract the serialized value from the call
        stored = mock_redis.setex.call_args.kwargs.get("value") or mock_redis.setex.call_args.args[2]
        parsed = json.loads(stored)
        assert parsed["id"] == str(uid)  # UUID becomes string

    @pytest.mark.asyncio
    async def test_corrupted_cache_returns_none(self, cache, mock_redis):
        """If stored value isn't valid JSON, treat as a miss (don't crash)."""
        mock_redis.get.return_value = "this is not json {{{{"
        result = await cache.get("corrupted:key")
        assert result is None


class TestSkillAssessmentCache:
    @pytest.mark.asyncio
    async def test_correct_key_used_for_skill_assessments(self, cache, mock_redis):
        """Key format must be consistent — wrong key = always a miss."""
        user_id = uuid.uuid4()
        await cache.get_skill_assessments(user_id)

        mock_redis.get.assert_called_once_with(f"skill_assessment:{user_id}")

    @pytest.mark.asyncio
    async def test_skill_assessment_ttl_is_5_minutes(self, cache, mock_redis):
        """5 minutes = 300 seconds. Verify the TTL contract."""
        user_id = uuid.uuid4()
        await cache.set_skill_assessments(user_id, [{"topic": "DSA", "score": 0.8}])

        call = mock_redis.setex.call_args
        ttl = call.kwargs.get("time") or call.args[1]
        assert ttl == 300

    @pytest.mark.asyncio
    async def test_invalidate_calls_delete(self, cache, mock_redis):
        user_id = uuid.uuid4()
        await cache.invalidate_skill_assessments(user_id)
        mock_redis.delete.assert_called_once_with(f"skill_assessment:{user_id}")


class TestSessionManagement:
    @pytest.mark.asyncio
    async def test_store_refresh_token_uses_correct_key(self, cache, mock_redis):
        user_id = uuid.uuid4()
        await cache.store_refresh_token(user_id, "somehash")
        call = mock_redis.setex.call_args
        key = call.kwargs.get("name") or call.args[0]
        assert key == f"session:{user_id}"

    @pytest.mark.asyncio
    async def test_revoke_session_deletes_correct_key(self, cache, mock_redis):
        user_id = uuid.uuid4()
        await cache.revoke_session(user_id)
        mock_redis.delete.assert_called_once_with(f"session:{user_id}")

    @pytest.mark.asyncio
    async def test_session_ttl_matches_config(self, cache, mock_redis):
        """Session TTL must match REFRESH_TOKEN_EXPIRE_DAYS from config."""
        from app.core.config import settings
        user_id = uuid.uuid4()
        await cache.store_refresh_token(user_id, "hash")

        expected_ttl = settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600
        call = mock_redis.setex.call_args
        ttl = call.kwargs.get("time") or call.args[1]
        assert ttl == expected_ttl


class TestDenylist:
    @pytest.mark.asyncio
    async def test_denylisted_token_detected(self, cache, mock_redis):
        mock_redis.get.return_value = "1"   # Key exists
        assert await cache.is_denylisted("some-jti") is True

    @pytest.mark.asyncio
    async def test_non_denylisted_token_passes(self, cache, mock_redis):
        mock_redis.get.return_value = None  # Key doesn't exist
        assert await cache.is_denylisted("legit-jti") is False

    @pytest.mark.asyncio
    async def test_denylist_key_format(self, cache, mock_redis):
        await cache.is_denylisted("abc123")
        mock_redis.get.assert_called_once_with("denylist:abc123")


class TestLeaderboard:
    @pytest.mark.asyncio
    async def test_update_leaderboard_calls_zadd(self, cache, mock_redis):
        """Leaderboard uses Redis Sorted Set — must call ZADD."""
        user_id = uuid.uuid4()
        await cache.update_leaderboard(user_id, 85.5)
        mock_redis.zadd.assert_called_once()

    @pytest.mark.asyncio
    async def test_leaderboard_trimmed_to_1000(self, cache, mock_redis):
        """Memory protection: keep only top 1000 entries."""
        user_id = uuid.uuid4()
        await cache.update_leaderboard(user_id, 90.0)
        mock_redis.zremrangebyrank.assert_called_once()
        # zremrangebyrank(key, 0, -1001) removes everything beyond rank 1000
        call_args = mock_redis.zremrangebyrank.call_args.args
        assert call_args[2] == -1001  # Keeps top 1000 (index 0 to 999)
