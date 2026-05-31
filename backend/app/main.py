"""
main.py — FastAPI application with full observability wired in
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints import auth, interview, code_review, roadmap
from app.core.config import settings
from app.core.logging import logger, configure_stdlib_logging
from app.core.metrics import metrics
from app.core.middleware import ObservabilityMiddleware, RateLimitMiddleware
from app.db.session import get_db, init_db
from app.services.health_service import HealthService


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ────────────────────────────────────────────────────────────────
    configure_stdlib_logging()

    logger.info(
        "application.starting",
        environment=settings.ENVIRONMENT,
        version="1.0.0",
    )

    await init_db()
    logger.info("database.connected")

    yield

    # ── Shutdown ───────────────────────────────────────────────────────────────
    logger.info("application.shutting_down")


app = FastAPI(
    title="DevMentor AI",
    version="1.0.0",
    docs_url="/docs" if settings.ENVIRONMENT == "development" else None,
    redoc_url="/redoc" if settings.ENVIRONMENT == "development" else None,
    lifespan=lifespan,
)

# ── Middleware ─────────────────────────────────────────────────────────────────
# Order matters: outermost runs first on request, last on response.
# ObservabilityMiddleware is outermost — it sees everything including
# time spent in rate limiting and CORS middleware.
app.add_middleware(ObservabilityMiddleware)
app.add_middleware(RateLimitMiddleware, requests_per_minute=settings.RATE_LIMIT_PER_MINUTE)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ────────────────────────────────────────────────────────────────────
app.include_router(auth.router,        prefix="/api/v1/auth",        tags=["auth"])
app.include_router(interview.router,   prefix="/api/v1/interview",   tags=["interview"])
app.include_router(code_review.router, prefix="/api/v1/code-review", tags=["code-review"])
app.include_router(roadmap.router,     prefix="/api/v1/roadmap",     tags=["roadmap"])


# ── Observability endpoints ────────────────────────────────────────────────────

@app.get("/health", tags=["monitoring"], include_in_schema=False)
async def liveness():
    """
    Liveness probe — is the process alive?
    Returns 200 immediately. Never checks external dependencies.
    Kubernetes kills and restarts the pod if this fails.
    """
    return {"status": "healthy", "service": "devmentor-backend", "version": "1.0.0"}


@app.get("/health/ready", tags=["monitoring"], include_in_schema=False)
async def readiness(db: AsyncSession = Depends(get_db)):
    """
    Readiness probe — can this pod accept traffic?
    Checks PostgreSQL, Redis, and ML service.
    Kubernetes stops routing traffic to this pod if this fails.
    Returns 503 if any critical dependency is unhealthy.
    """
    try:
        from app.db.redis import get_redis
        from app.services.ml_client import get_ml_client
        redis = await get_redis()
        ml_client = get_ml_client()
    except Exception:
        redis = None
        ml_client = None

    service = HealthService(db=db, redis=redis, ml_client=ml_client)
    result = await service.full_check()

    status_code = 200 if result["status"] in ("healthy", "degraded") else 503
    from fastapi.responses import JSONResponse
    return JSONResponse(content=result, status_code=status_code)


@app.get("/metrics", tags=["monitoring"], include_in_schema=False)
async def prometheus_metrics():
    """
    Prometheus metrics endpoint.
    Scraped by Prometheus every 15 seconds.
    Returns metrics in Prometheus exposition format.

    Add to prometheus.yml:
      scrape_configs:
        - job_name: devmentor-backend
          static_configs:
            - targets: ['backend:8000']
    """
    return Response(
        content=metrics.prometheus_output(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
        # WHY this specific content type?
        #   Prometheus requires exactly this media type to parse the response.
        #   Any other type → Prometheus ignores the endpoint.
    )
