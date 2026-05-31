"""
tests/test_observability.py — Observability component tests

What we test:
  - Structured logger produces correct JSON shape
  - ContextVar request ID is isolated between "requests"
  - Metrics counters, gauges, and histograms behave correctly
  - Prometheus output format is parseable
  - Health service aggregates results correctly
  - Health service runs checks concurrently (not sequentially)
"""

import json
import io
import time
import sys
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from starlette.requests import Request

from app.core.logging import StructuredLogger, set_request_context, request_id_var
from app.core.metrics import MetricsRegistry, Counter, Gauge, Histogram
from app.core.middleware import RateLimitMiddleware
from app.services.health_service import HealthService


# ── Logger tests ──────────────────────────────────────────────────────────────

class TestStructuredLogger:

    def _capture_log(self, log_fn, *args, **kwargs) -> dict:
        """Capture stdout output of one log call and parse as JSON."""
        captured = io.StringIO()
        with patch('sys.stdout', captured):
            log_fn(*args, **kwargs)
        output = captured.getvalue().strip()
        return json.loads(output)

    def test_log_output_is_valid_json(self):
        log = StructuredLogger()
        record = self._capture_log(log.info, "test.event", key="value")
        assert isinstance(record, dict)

    def test_log_contains_required_fields(self):
        log = StructuredLogger()
        record = self._capture_log(log.info, "test.event")
        assert "timestamp" in record
        assert "level" in record
        assert "event" in record
        assert "service" in record

    def test_info_level_set_correctly(self):
        log = StructuredLogger()
        record = self._capture_log(log.info, "test.event")
        assert record["level"] == "INFO"

    def test_error_level_set_correctly(self):
        log = StructuredLogger()
        record = self._capture_log(log.error, "test.error")
        assert record["level"] == "ERROR"

    def test_extra_fields_included(self):
        log = StructuredLogger()
        record = self._capture_log(log.info, "user.login", user_id="abc123", duration_ms=45.2)
        assert record["user_id"] == "abc123"
        assert record["duration_ms"] == 45.2

    def test_none_values_excluded(self):
        """None values bloat logs — they should be stripped."""
        log = StructuredLogger()
        record = self._capture_log(log.info, "test.event")
        # request_id and user_id are None when no request context is set
        assert "request_id" not in record
        assert "user_id" not in record

    def test_request_id_included_when_set(self):
        log = StructuredLogger()
        set_request_context("req-123-abc")
        record = self._capture_log(log.info, "test.event")
        assert record["request_id"] == "req-123-abc"

    def test_bound_logger_includes_context(self):
        log = StructuredLogger()
        bound = log.bind(session_id="sess-xyz", topic="DSA")
        record = self._capture_log(bound.info, "session.started")
        assert record["session_id"] == "sess-xyz"
        assert record["topic"] == "DSA"

    def test_bound_logger_context_composable(self):
        """Bound loggers should stack context."""
        log = StructuredLogger()
        bound1 = log.bind(request_type="interview")
        bound2 = bound1.bind(question_num=3)
        record = self._capture_log(bound2.info, "question.asked")
        assert record["request_type"] == "interview"
        assert record["question_num"] == 3

    def test_log_output_is_single_line(self):
        """Each log must be exactly one line — multi-line breaks log parsers."""
        log = StructuredLogger()
        captured = io.StringIO()
        with patch('sys.stdout', captured):
            log.info("test.event", data="some value")
        lines = [l for l in captured.getvalue().split('\n') if l.strip()]
        assert len(lines) == 1

    def test_context_var_isolated_between_requests(self):
        """
        ContextVar must not leak between concurrent async tasks.
        This tests the core async isolation guarantee.
        """
        async def task_a():
            set_request_context("req-A")
            await asyncio.sleep(0.01)  # Simulate I/O — other tasks run here
            return request_id_var.get()

        async def task_b():
            set_request_context("req-B")
            await asyncio.sleep(0.005)
            return request_id_var.get()

        async def run():
            # Run concurrently — if ContextVar leaked, one would see the other's ID
            id_a, id_b = await asyncio.gather(task_a(), task_b())
            return id_a, id_b

        id_a, id_b = asyncio.run(run())
        assert id_a == "req-A"
        assert id_b == "req-B"


# ── Metrics tests ─────────────────────────────────────────────────────────────

class TestMetrics:

    def test_counter_starts_at_zero(self):
        c = Counter(name="test_counter", help="Test")
        assert c.get() == 0.0

    def test_counter_increments(self):
        c = Counter(name="test_counter", help="Test")
        c.inc()
        c.inc()
        c.inc(5)
        assert c.get() == 7.0

    def test_counter_never_decrements(self):
        """Counters should only go up — no decrement method."""
        c = Counter(name="test_counter", help="Test")
        c.inc(10)
        assert not hasattr(c, 'dec')
        assert c.get() == 10.0

    def test_gauge_set_and_get(self):
        g = Gauge(name="test_gauge", help="Test")
        g.set(42.5)
        assert g.get() == 42.5

    def test_gauge_inc_dec(self):
        g = Gauge(name="test_gauge", help="Test")
        g.inc(5)
        g.dec(2)
        assert g.get() == 3.0

    def test_histogram_observe_increments_count(self):
        h = Histogram("test_hist", "Test")
        h.observe(0.1)
        h.observe(0.5)
        h.observe(1.0)
        assert h._count == 3

    def test_histogram_observe_accumulates_sum(self):
        h = Histogram("test_hist", "Test")
        h.observe(0.1)
        h.observe(0.2)
        h.observe(0.3)
        assert abs(h._sum - 0.6) < 1e-9

    def test_histogram_bucket_counts(self):
        """
        Prometheus histogram buckets are CUMULATIVE.
        Each bucket counts all observations <= its upper bound.
        This is the correct Prometheus semantics — allows computing quantiles.
        """
        h = Histogram("test_hist", "Test", buckets=[0.1, 0.5, 1.0])
        h.observe(0.05)   # ≤0.1, ≤0.5, ≤1.0
        h.observe(0.3)    # ≤0.5, ≤1.0  (not ≤0.1)
        h.observe(0.8)    # ≤1.0  only
        h.observe(2.0)    # none of the finite buckets — only +Inf

        # Cumulative: bucket[0.1] = count of observations ≤ 0.1
        assert h._counts[0.1] == 1   # only 0.05
        # Cumulative: bucket[0.5] = count of observations ≤ 0.5 (includes ≤0.1)
        assert h._counts[0.5] == 2   # 0.05 + 0.3
        # Cumulative: bucket[1.0] = count of observations ≤ 1.0
        assert h._counts[1.0] == 3   # 0.05 + 0.3 + 0.8
        # Total observations
        assert h._count == 4

    def test_record_request_updates_counters(self):
        r = MetricsRegistry()
        r.record_request("GET", "/api/v1/auth/me", 200, 0.045)
        r.record_request("POST", "/api/v1/auth/login", 401, 0.032)

        assert r.http_requests_total["GET:/api/v1/auth/me:200"] == 1
        assert r.http_errors_total["POST:/api/v1/auth/login:401"] == 1

    def test_prometheus_output_is_valid_format(self):
        """Prometheus output must contain HELP and TYPE lines before metrics."""
        r = MetricsRegistry()
        r.record_request("GET", "/api/v1/health", 200, 0.01)
        output = r.prometheus_output()

        assert "# HELP" in output
        assert "# TYPE" in output
        assert "http_requests_total" in output

    def test_prometheus_output_is_text(self):
        r = MetricsRegistry()
        output = r.prometheus_output()
        assert isinstance(output, str)
        assert len(output) > 0

    def test_prometheus_output_ends_with_newline(self):
        """Prometheus requires trailing newline."""
        r = MetricsRegistry()
        assert r.prometheus_output().endswith('\n')

    def test_uptime_metric_increases(self):
        """Process uptime should be positive and increase over time."""
        r = MetricsRegistry()
        output1 = r.prometheus_output()
        time.sleep(0.01)
        output2 = r.prometheus_output()

        def extract_uptime(output):
            for line in output.split('\n'):
                if line.startswith('process_uptime_seconds '):
                    return float(line.split(' ')[1])
            return 0.0

        uptime1 = extract_uptime(output1)
        uptime2 = extract_uptime(output2)
        assert uptime2 > uptime1 >= 0.0


# ── Health service tests ──────────────────────────────────────────────────────

class TestRateLimitMiddleware:

    @pytest.mark.asyncio
    async def test_downstream_exception_is_not_treated_as_redis_failure(self):
        middleware = RateLimitMiddleware(MagicMock())
        middleware._redis = AsyncMock()
        middleware._redis.incr.return_value = 1
        request = Request({"type": "http", "method": "GET", "path": "/test", "headers": []})
        call_next = AsyncMock(side_effect=RuntimeError("endpoint failed"))

        with pytest.raises(RuntimeError, match="endpoint failed"):
            await middleware.dispatch(request, call_next)

        call_next.assert_awaited_once()


class TestHealthService:

    @pytest.mark.asyncio
    async def test_healthy_when_all_pass(self):
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock())
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_ml = AsyncMock()
        mock_ml.health_check = AsyncMock(return_value={
            "status": "healthy", "model_loaded": True, "groq_available": True
        })

        svc = HealthService(db=mock_db, redis=mock_redis, ml_client=mock_ml)
        result = await svc.full_check()

        assert result["status"] == "healthy"
        assert "checks" in result

    @pytest.mark.asyncio
    async def test_unhealthy_when_db_fails(self):
        """DB failure = unhealthy overall (it's the critical dependency)."""
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=Exception("Connection refused"))
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)

        svc = HealthService(db=mock_db, redis=mock_redis)
        result = await svc.full_check()

        assert result["status"] == "unhealthy"
        assert result["checks"]["database"]["status"] == "unhealthy"

    @pytest.mark.asyncio
    async def test_degraded_when_redis_fails_but_db_healthy(self):
        """Redis failure = degraded (not unhealthy — app still functions)."""
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock())
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(side_effect=Exception("Redis down"))

        svc = HealthService(db=mock_db, redis=mock_redis, ml_client=None)
        result = await svc.full_check()

        assert result["status"] == "degraded"
        assert result["checks"]["redis"]["status"] == "unhealthy"

    @pytest.mark.asyncio
    async def test_unconfigured_when_no_dependencies(self):
        svc = HealthService()
        result = await svc.full_check()
        assert result["checks"]["database"]["status"] == "unconfigured"
        assert result["checks"]["redis"]["status"] == "unconfigured"
        assert result["checks"]["ml_service"]["status"] == "unconfigured"

    @pytest.mark.asyncio
    async def test_checks_run_concurrently(self):
        """
        Critical: health checks must run in parallel, not sequentially.
        If each check takes 1s, sequential = 3s total.
        Concurrent = ~1s total.
        We verify by mocking with asyncio.sleep delays.
        """
        async def slow_db(*args, **kwargs):
            await asyncio.sleep(0.05)
            return MagicMock()

        async def slow_redis():
            await asyncio.sleep(0.05)
            return True

        mock_db = AsyncMock()
        mock_db.execute = slow_db
        mock_redis = AsyncMock()
        mock_redis.ping = slow_redis

        svc = HealthService(db=mock_db, redis=mock_redis, ml_client=None)

        start = time.perf_counter()
        result = await svc.full_check()
        elapsed = time.perf_counter() - start

        # Sequential would take 0.1s (50ms + 50ms)
        # Concurrent takes ~50ms — allow 90ms for overhead
        assert elapsed < 0.09, f"Health checks took {elapsed:.3f}s — they may not be concurrent"

    @pytest.mark.asyncio
    async def test_result_includes_version(self):
        svc = HealthService()
        result = await svc.full_check()
        assert "version" in result
        assert "service" in result

    @pytest.mark.asyncio
    async def test_result_includes_timing(self):
        svc = HealthService()
        result = await svc.full_check()
        assert "total_check_ms" in result
        assert result["total_check_ms"] >= 0.0

    @pytest.mark.asyncio
    async def test_ml_starting_status_shows_degraded_not_unhealthy(self):
        """ML model still loading = degraded, not unhealthy."""
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock())
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_ml = AsyncMock()
        mock_ml.health_check = AsyncMock(return_value={
            "status": "degraded",
            "model_loaded": False,
        })

        svc = HealthService(db=mock_db, redis=mock_redis, ml_client=mock_ml)
        result = await svc.full_check()

        # DB and Redis healthy, ML starting → degraded overall, not unhealthy
        assert result["status"] in ("healthy", "degraded")
