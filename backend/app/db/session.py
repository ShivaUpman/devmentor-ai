"""
db/session.py — Async database session management

WHY connection pooling?
  Opening a new database connection is expensive (~100ms, requires TCP handshake,
  auth negotiation, SSL if configured). A connection pool keeps N connections open
  and reuses them across requests.

  Without pooling: 100 simultaneous users = 100 connection attempts = slow, or DB refusal.
  With pooling: 100 users share a pool of 10 connections = fast, controlled.

  Interview question: "What is a connection pool? What happens if pool_size is too small?"
  Answer: Requests queue and time out. pool_size + max_overflow = hard cap on DB connections.
"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


# ── Engine ─────────────────────────────────────────────────────────────────────
# The engine is the lowest-level connection factory.
# create_async_engine uses asyncpg under the hood — fully non-blocking.
#
# pool_size: persistent connections kept alive
# max_overflow: extra connections allowed under burst load (temporary)
# pool_pre_ping: before handing a connection to your code, ping it.
#   WHY? PostgreSQL closes idle connections after a timeout.
#   Without pre_ping, you'd get "connection closed" errors on old connections.
engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    echo=settings.DEBUG,  # logs every SQL query in development — very useful
)


# ── Session factory ─────────────────────────────────────────────────────────────
# async_sessionmaker creates AsyncSession objects.
# expire_on_commit=False: after a commit, ORM objects remain usable.
#   WHY? In async code, accessing an expired attribute would trigger another
#   DB query, which in async context requires an open session. Turning this off
#   avoids confusing "DetachedInstanceError" bugs.
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


# ── Base model ─────────────────────────────────────────────────────────────────
# All SQLAlchemy ORM models inherit from this.
# DeclarativeBase registers them with the metadata system so Alembic
# can detect table changes and generate migrations automatically.
class Base(DeclarativeBase):
    pass


# ── Dependency ─────────────────────────────────────────────────────────────────
# WHY use a generator function as a FastAPI dependency?
#   This is FastAPI's dependency injection pattern.
#   The "yield" splits the function: code before yield = setup (open session),
#   code after yield = teardown (close session).
#   FastAPI guarantees the session is ALWAYS closed, even if the endpoint crashes.
#
#   Usage in any endpoint:
#     async def my_endpoint(db: AsyncSession = Depends(get_db)):
async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ── Startup initializer ─────────────────────────────────────────────────────────
async def init_db():
    """
    Called once at app startup (in main.py lifespan).
    In development, creates tables if they don't exist.
    In production, we use Alembic migrations instead.
    """
    async with engine.begin() as conn:
        # Import all models so SQLAlchemy knows about them
        from app.models import user, session, submission  # noqa: F401
        # Reflect the schema (development convenience — use Alembic for production)
        await conn.run_sync(Base.metadata.create_all)
