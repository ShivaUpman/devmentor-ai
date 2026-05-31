"""
models/user.py — User ORM model

WHY SQLAlchemy ORM instead of raw SQL?
  ORM = Object Relational Mapper. It lets you work with database rows as Python
  objects instead of writing SQL strings manually.

  Raw SQL: cursor.execute("SELECT * FROM users WHERE id = %s", [user_id])
  ORM:     session.get(User, user_id)

  Benefits:
    - Type safety — Python type hints on every column
    - Composable queries — chain .filter(), .order_by(), .limit() like Python
    - Migration support — Alembic detects model changes automatically
    - No SQL injection risk when using the ORM properly

  Tradeoff: For very complex queries (multi-table aggregations, window functions),
  raw SQL is often clearer. Real-world code uses both: ORM for CRUD, raw SQL for analytics.

Interview question: "When would you use raw SQL over an ORM?"
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Enum, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class User(Base):
    """
    The central entity — every other table links back to this one.

    WHY __tablename__ explicit?
      SQLAlchemy can infer it ("User" → "user"), but explicit is better.
      Avoids surprises when class names don't map obviously to table names.
    """
    __tablename__ = "users"

    # ── Primary key ────────────────────────────────────────────────────────────
    # WHY UUID and not Integer?
    #   - Globally unique: safe to merge data from different environments
    #   - Non-sequential: prevents enumeration attacks (can't guess /users/1, /users/2)
    #   - Generated client-side: no DB round-trip needed to get the ID before insert
    #
    # WHY server_default instead of default?
    #   server_default: the DB generates the value. No Python code needed.
    #     If you INSERT without specifying id, Postgres fills it in.
    #   default: Python generates the value before sending to DB.
    #   For UUIDs we use server_default=gen_random_uuid() — pure DB, no Python dep.
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )

    # ── Core fields ────────────────────────────────────────────────────────────
    # unique=True creates a UNIQUE constraint — PostgreSQL enforces this at DB level.
    # index=True creates a B-tree index for fast lookups.
    # WHY index on email?
    #   Login queries: SELECT * FROM users WHERE email = ?
    #   Without an index: full table scan — O(n). With index: O(log n).
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
    )

    # NEVER store plain passwords. This field always holds a bcrypt hash.
    # bcrypt output is always 60 chars. String(60) is exact.
    hashed_password: Mapped[str] = mapped_column(String(60), nullable=False)

    full_name: Mapped[str] = mapped_column(String(100), nullable=False)

    # WHY Enum for role?
    #   Enum constrains values at the DB level — Postgres rejects anything not in the list.
    #   Better than a String — prevents typos like "Admim" or "superuser".
    role: Mapped[str] = mapped_column(
        Enum("user", "admin", name="user_role_enum"),
        nullable=False,
        server_default="user",
    )

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    # ── Timestamps ─────────────────────────────────────────────────────────────
    # WHY server_default=func.now()?
    #   The DB fills this in on INSERT. Python doesn't need to know the time.
    #   Consistent across all inserts, even batch inserts from scripts.
    #
    # WHY timezone=True?
    #   Always store UTC. Display in user's local time in the frontend.
    #   Storing timezone-naive datetimes is a classic bug that causes
    #   "ghost events" when clocks change or servers are in different regions.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),  # Automatically updates on every UPDATE
    )

    # ── Relationships ──────────────────────────────────────────────────────────
    # WHY lazy="select" (default) vs lazy="joined"?
    #   lazy="select": loads related objects in a SEPARATE query when accessed.
    #     user.sessions → triggers: SELECT * FROM interview_sessions WHERE user_id=?
    #   lazy="joined": loads related objects in the SAME query with a JOIN.
    #
    #   For lists (one-to-many), selectin loading is usually better than joined —
    #   joined loading for collections produces duplicate rows (cartesian product).
    #
    # WHY back_populates?
    #   Creates a bidirectional relationship:
    #     user.sessions → list of InterviewSession
    #     session.user → the User
    #   Without it: one-directional only, can't navigate from child to parent.
    sessions: Mapped[list["InterviewSession"]] = relationship(
        "InterviewSession",
        back_populates="user",
        cascade="all, delete-orphan",  # Deleting a user deletes their sessions
        lazy="select",
    )
    skill_assessments: Mapped[list["SkillAssessment"]] = relationship(
        "SkillAssessment",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    roadmap_items: Mapped[list["RoadmapItem"]] = relationship(
        "RoadmapItem",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    # ── Table-level constraints and indexes ────────────────────────────────────
    __table_args__ = (
        # Composite index: speeds up queries filtering by both role AND is_active
        # e.g., "fetch all active admins" — common admin dashboard query
        Index("ix_users_role_active", "role", "is_active"),
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email}>"
