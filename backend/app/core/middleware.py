"""
core/middleware.py — Production-grade observability middleware

This replaces the Module 4 stub with:
  1. Request ID generation and propagation (tracing)
  2. Structured JSON logging for every request
  3. Prometheus metrics recording
  4. Performance timing
  5. Redis-backed rate limiting
  6. Graceful error handling with logging

WHY middleware for all of this?
  Cross-cutting concerns — they apply to every request regardless of endpoint.
  Single place to maintain. Zero duplication. Endpoints stay clean.

  The middleware stack runs like this for each request:
    LoggingMiddleware.before → RateLimit.before → Endpoint → RateLimit.after → Logging.after

  The outermost middleware sees everything — start time, final status code, duration.
"""

import time
import uuid
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.logging import logger, set_request_context
from app.core.metrics import metrics

# Paths that should not be logged/metered — reduce noise
EXCLUDED_PATHS = {'/health', '/health/ready', '/metrics', '/docs', '/redoc', '/openapi.json'}


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """
    Combines request logging + metrics + tracing into one middleware.

    WHY one middleware for all three?
      They all need the same data: request_id, start_time, method, path.
      Computing these once and sharing is more efficient than three middlewares.
      The overhead is: one UUID generation + one time.perf_counter() call per request.

    Request lifecycle:
      → Generate request_id
      → Set ContextVar (makes request_id available to all log calls in this request)
      → Record start time
      → Call endpoint
      → Log result (method, path, status, duration)
      → Record metrics
      → Add X-Request-ID to response headers
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Generate or propagate request ID
        # WHY check for existing header?
        #   Nginx may have already generated a request ID.
        #   Downstream services should inherit the ID from upstream.
        #   This is how distributed tracing works: one ID for the entire call chain.
        request_id = (
            request.headers.get('X-Request-ID')
            or str(uuid.uuid4())
        )

        # Set in ContextVar — now available to all log calls in this request
        set_request_context(request_id)

        # Exclude noisy health/metrics paths from detailed logging
        path = request.url.path
        is_excluded = path in EXCLUDED_PATHS

        start_time = time.perf_counter()
        client_ip = request.client.host if request.client else 'unknown'
        method = request.method

        # Log request received (before processing)
        if not is_excluded:
            logger.info(
                "request.received",
                method=method,
                path=path,
                client_ip=client_ip,
                user_agent=request.headers.get('user-agent', '')[:100],
            )

        # Track active connections
        metrics.active_connections.inc()

        try:
            response = await call_next(request)
            duration = time.perf_counter() - start_time
            status_code = response.status_code

            # Normalize paths for metrics to prevent cardinality explosion
            # WHY normalize?
            #   /api/v1/users/550e8400-.../sessions creates a unique time series
            #   for EVERY user — millions of series, Prometheus runs out of memory.
            #   Normalize to /api/v1/users/{id}/sessions — one time series for all users.
            normalized_path = self._normalize_path(path)

            if not is_excluded:
                # Structured log — every field is queryable
                log_fn = logger.warning if status_code >= 400 else logger.info
                log_fn(
                    "request.completed",
                    method=method,
                    path=path,
                    status_code=status_code,
                    duration_ms=round(duration * 1000, 2),
                    client_ip=client_ip,
                )

                # Record Prometheus metrics
                metrics.record_request(method, normalized_path, status_code, duration)

            # Propagate request ID to client
            # WHY send it back?
            #   Users can include it in bug reports.
            #   Frontend can log it alongside UI errors.
            #   Support team can search logs by this ID.
            response.headers['X-Request-ID'] = request_id
            response.headers['X-Response-Time'] = f'{round(duration * 1000, 2)}ms'

            return response

        except Exception as exc:
            duration = time.perf_counter() - start_time
            logger.error(
                "request.error",
                method=method,
                path=path,
                duration_ms=round(duration * 1000, 2),
                error=str(exc)[:200],
                error_type=type(exc).__name__,
            )
            metrics.record_request(method, self._normalize_path(path), 500, duration)
            raise
        finally:
            metrics.active_connections.dec()

    def _normalize_path(self, path: str) -> str:
        """
        Replace dynamic path segments with placeholders.

        /api/v1/users/550e8400-e29b-41d4/sessions → /api/v1/users/{id}/sessions
        /api/v1/roadmap/items/a1b2c3              → /api/v1/roadmap/items/{id}

        WHY this matters for metrics:
          Each unique label combination = one Prometheus time series.
          One series per user ID → millions of series → OOM crash.
          One series per route pattern → manageable cardinality.

          This is called "high cardinality" — a common Prometheus footgun.
          Real systems at Uber/Netflix have strict cardinality budgets.
        """
        import re
        # UUIDs
        path = re.sub(
            r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
            '{id}',
            path,
        )
        # Pure numeric IDs
        path = re.sub(r'/\d{2,}', '/{id}', path)
        return path


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Redis-backed rate limiting with structured logging.

    From Module 4 — now enhanced with:
      - Logging of rate-limited requests (security audit trail)
      - Metrics recording (track rate limit hit rate)
      - Different limits for different endpoints (auth endpoints get stricter limits)
    """

    # Stricter limits for sensitive endpoints
    ENDPOINT_LIMITS = {
        '/api/v1/auth/login': 10,       # 10 login attempts per minute per IP
        '/api/v1/auth/register': 5,     # 5 registrations per minute per IP
    }

    def __init__(self, app, requests_per_minute: int = 60):
        super().__init__(app)
        self.default_limit = requests_per_minute
        self._redis = None

    async def _get_redis(self):
        if self._redis is None:
            try:
                import redis.asyncio as aioredis
                from app.core.config import settings
                self._redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
            except Exception:
                return None
        return self._redis

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path in {'/health', '/health/ready', '/metrics'}:
            return await call_next(request)

        client_ip = request.client.host if request.client else 'unknown'
        path = request.url.path
        limit = self.ENDPOINT_LIMITS.get(path, self.default_limit)
        current_minute = int(time.time() // 60)
        key = f'rate_limit:{client_ip}:{current_minute}'

        redis = await self._get_redis()
        if redis:
            try:
                count = await redis.incr(key)
                if count == 1:
                    await redis.expire(key, 90)
            except Exception as e:
                logger.warning("rate_limit.redis_error", error=str(e)[:100])
                # Fail open — don't block traffic when Redis is down
            else:
                if count > limit:
                    logger.warning(
                        "rate_limit.exceeded",
                        client_ip=client_ip,
                        path=path,
                        count=count,
                        limit=limit,
                    )
                    from fastapi.responses import JSONResponse
                    return JSONResponse(
                        status_code=429,
                        content={"detail": "Too many requests. Please slow down."},
                        headers={
                            "Retry-After": "60",
                            "X-RateLimit-Limit": str(limit),
                            "X-RateLimit-Remaining": "0",
                            "X-RateLimit-Reset": str((current_minute + 1) * 60),
                        },
                    )

                response = await call_next(request)
                response.headers["X-RateLimit-Limit"] = str(limit)
                response.headers["X-RateLimit-Remaining"] = str(max(0, limit - count))
                return response

        return await call_next(request)
