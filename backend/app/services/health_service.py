"""
services/health_service.py — Deep health checks

WHY two health check endpoints?

  GET /health (liveness probe):
    "Is the process alive?"
    Returns 200 immediately — no external checks.
    Kubernetes uses this to know if the pod should be killed and restarted.
    If this fails: the process is frozen, OOM-killed, or deadlocked.
    NEVER check external dependencies here — a DB outage would kill all pods.

  GET /health/ready (readiness probe):
    "Can this instance accept traffic?"
    Checks all dependencies: PostgreSQL, Redis, ML service.
    Kubernetes uses this to know if the pod should receive traffic.
    If this fails: pod stays alive but is removed from the load balancer.
    The pod isn't killed — it waits for dependencies to recover.

  This distinction is critical and frequently asked in interviews.
  Confusion causes: either all pods get killed during a DB outage (wrong!)
  or broken pods keep receiving traffic (also wrong!).

  Real-world example: during a Redis restart, readiness → 503 for ~5s,
  so requests go to other healthy pods. Liveness stays 200.
  After Redis recovers, readiness → 200, pod rejoins the pool.
  Zero dropped requests, zero pod restarts.

Interview question: "What's the difference between liveness and readiness probes?"
  Liveness: failing → Kubernetes kills and restarts the pod
  Readiness: failing → Kubernetes stops sending traffic to the pod
  Startup probe: disables liveness/readiness checks until app is initialized
"""

import time
from typing import Optional
import asyncio

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text


class HealthService:
    """
    Performs deep health checks on all system dependencies.

    Each check has a timeout — a hung check shouldn't block the health endpoint.
    A health check that takes 30s is worse than returning 'degraded'.

    WHY check each dependency independently?
      Partial availability is useful information.
      "DB healthy, Redis degraded, ML unavailable" tells you exactly what's wrong.
      "unhealthy" tells you nothing.
    """

    def __init__(
        self,
        db: Optional[AsyncSession] = None,
        redis=None,
        ml_client=None,
    ):
        self.db = db
        self.redis = redis
        self.ml_client = ml_client

    async def check_database(self) -> dict:
        """
        Verify PostgreSQL connectivity and response time.

        WHY SELECT 1 and not a table query?
          SELECT 1 doesn't touch any tables — it tests the connection only.
          A table query could fail due to missing tables or permissions,
          which is a different failure mode from "DB is down".
          We want to know: can we reach the DB? Not: is our schema correct?
        """
        if not self.db:
            return {"status": "unconfigured"}

        start = time.perf_counter()
        try:
            await asyncio.wait_for(
                self.db.execute(text("SELECT 1")),
                timeout=3.0,
            )
            duration_ms = (time.perf_counter() - start) * 1000
            return {
                "status": "healthy",
                "response_time_ms": round(duration_ms, 2),
                # WHY include response time?
                #   A DB that responds in 2500ms is technically "healthy" but
                #   will cause timeouts in production. Slow health = early warning.
            }
        except asyncio.TimeoutError:
            return {"status": "timeout", "detail": "DB query exceeded 3s"}
        except Exception as e:
            return {"status": "unhealthy", "detail": str(e)[:100]}

    async def check_redis(self) -> dict:
        """
        Verify Redis connectivity and response time.

        PING → PONG is Redis's built-in health check command.
        If Redis is down: sessions can't be validated, rate limiting fails.
        Both degrade gracefully (fail open) but users may see stale data.
        """
        if not self.redis:
            return {"status": "unconfigured"}

        start = time.perf_counter()
        try:
            result = await asyncio.wait_for(
                self.redis.ping(),
                timeout=2.0,
            )
            duration_ms = (time.perf_counter() - start) * 1000
            if result:
                return {
                    "status": "healthy",
                    "response_time_ms": round(duration_ms, 2),
                }
            return {"status": "unhealthy", "detail": "PING returned false"}
        except asyncio.TimeoutError:
            return {"status": "timeout", "detail": "Redis PING exceeded 2s"}
        except Exception as e:
            return {"status": "unhealthy", "detail": str(e)[:100]}

    async def check_ml_service(self) -> dict:
        """
        Verify the ML service is reachable and models are loaded.

        WHY check model_loaded specifically?
          The ML service may be running but still loading the 90MB model.
          During those ~3 seconds: the service accepts connections but
          returns 503 on /evaluate. We want to know this state.
          health.model_loaded=false → report as "starting" not "unhealthy".
        """
        if not self.ml_client:
            return {"status": "unconfigured"}

        start = time.perf_counter()
        try:
            result = await asyncio.wait_for(
                self.ml_client.health_check(),
                timeout=5.0,
            )
            duration_ms = (time.perf_counter() - start) * 1000

            if result.get("status") == "healthy":
                return {
                    "status": "healthy",
                    "model_loaded": result.get("model_loaded", False),
                    "groq_available": result.get("groq_available", False),
                    "response_time_ms": round(duration_ms, 2),
                }
            elif not result.get("model_loaded"):
                return {
                    "status": "starting",
                    "detail": "Model still loading",
                    "response_time_ms": round(duration_ms, 2),
                }
            return {"status": "degraded", "detail": result.get("status")}
        except asyncio.TimeoutError:
            return {"status": "timeout", "detail": "ML service exceeded 5s"}
        except Exception as e:
            return {"status": "unreachable", "detail": str(e)[:100]}

    async def full_check(self) -> dict:
        """
        Run all health checks concurrently and aggregate results.

        WHY asyncio.gather and not sequential awaits?
          Sequential: DB(2s) + Redis(1s) + ML(3s) = 6 seconds total.
          Concurrent: max(2s, 1s, 3s) = 3 seconds total.
          A 6-second health check is useless — load balancers timeout at 5s.
          Concurrency is why async matters here.

        Aggregate status:
          "healthy":  all checks pass
          "degraded": some checks pass (partial availability)
          "unhealthy": critical checks fail (DB down = unhealthy)
        """
        start = time.perf_counter()

        # Run all checks concurrently
        db_result, redis_result, ml_result = await asyncio.gather(
            self.check_database(),
            self.check_redis(),
            self.check_ml_service(),
            return_exceptions=False,
        )

        total_ms = (time.perf_counter() - start) * 1000

        # Determine overall status
        # WHY is DB the critical dependency?
        #   Without the DB: auth fails, data can't be read or written.
        #   Without Redis: caching degrades but app still functions.
        #   Without ML: scoring is delayed but answers are saved.
        #   DB is the single hard dependency.
        db_status = db_result.get("status")
        redis_status = redis_result.get("status")
        ml_status = ml_result.get("status")

        if db_status == "healthy":
            if redis_status == "healthy" and ml_status in ("healthy", "starting"):
                overall = "healthy"
            else:
                overall = "degraded"
        else:
            overall = "unhealthy"

        return {
            "status": overall,
            "total_check_ms": round(total_ms, 2),
            "checks": {
                "database": db_result,
                "redis": redis_result,
                "ml_service": ml_result,
            },
            # WHY include version info in health response?
            #   "What's currently deployed?" is the first debugging question.
            #   Health check response answers it without SSH access.
            "version": "1.0.0",
            "service": "devmentor-backend",
        }
