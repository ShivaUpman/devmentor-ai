"""
config.py — Centralized application configuration

WHY Pydantic Settings?
  Configuration is one of the 12-Factor App principles (factor III: Config).
  The rule: separate config from code. Never hardcode secrets.

  Pydantic Settings reads from:
    1. Environment variables (highest priority — used in production)
    2. .env file (used in local development)
    3. Default values (used if nothing else is set)

  This gives you ONE typed, validated config object used everywhere in the app.
  If DATABASE_URL is missing, the app crashes at startup with a clear error —
  not at 2am when a query finally runs.

Interview question: "How do you handle secrets in a 12-Factor app?"
Answer: Environment variables injected at runtime, never committed to git.
"""

from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ── App ────────────────────────────────────────────────────────────────────
    ENVIRONMENT: str = "development"          # development | production | test
    SECRET_KEY: str = "change-me-in-production"  # Used to sign JWT tokens
    DEBUG: bool = True

    # ── Database ───────────────────────────────────────────────────────────────
    # WHY a connection string (DSN)?
    #   Contains everything needed to connect: driver, user, password, host, db.
    #   Format: postgresql+asyncpg://user:password@host:port/dbname
    #   We use asyncpg driver for non-blocking async DB calls.
    DATABASE_URL: str = "postgresql+asyncpg://devmentor:devmentor@postgres:5432/devmentor"

    # For Alembic (sync driver — Alembic doesn't support asyncpg)
    SYNC_DATABASE_URL: str = "postgresql://devmentor:devmentor@postgres:5432/devmentor"

    # ── Redis ──────────────────────────────────────────────────────────────────
    REDIS_URL: str = "redis://redis:6379/0"

    # ── JWT ────────────────────────────────────────────────────────────────────
    # WHY two different expiry times?
    #   Access tokens: short-lived (30 min). If stolen, damage is time-limited.
    #   Refresh tokens: long-lived (7 days). Used only to get new access tokens.
    #   This is the industry standard pattern used by Google, GitHub, etc.
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    ALGORITHM: str = "HS256"   # HMAC-SHA256

    # ── CORS ───────────────────────────────────────────────────────────────────
    ALLOWED_ORIGINS: List[str] = [
        "http://localhost:3000",    # Next.js dev server
        "http://localhost",         # Nginx in Docker
    ]

    # ── ML Service ─────────────────────────────────────────────────────────────
    # WHY a separate ML service URL?
    #   ML models are CPU/memory-heavy. Separating them lets you scale
    #   ML independently from the API. In production you might run 10 API pods
    #   but only 2 ML pods (ML is expensive, API is cheap).
    ML_SERVICE_URL: str = "http://ml:8001"

    # ── Groq LLM ───────────────────────────────────────────────────────────────
    # Free tier: 14,400 req/day on llama-3.3-70b-versatile
    # Get your key at console.groq.com
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.3-70b-versatile"

    # ── Rate Limiting ──────────────────────────────────────────────────────────
    RATE_LIMIT_PER_MINUTE: int = 60

    # ── Pydantic Settings config ────────────────────────────────────────────────
    # Tells Pydantic Settings to read from a .env file
    # env_file_encoding handles files with special characters (non-ASCII secrets)
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )


# WHY a module-level singleton?
#   Pydantic Settings reads and validates ALL config at import time.
#   This means: bad config = crash at startup, not at runtime.
#   Import this settings object everywhere: from app.core.config import settings
settings = Settings()
