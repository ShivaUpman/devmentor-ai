"""
models/session.py — InterviewSession and SessionQuestion ORM models

These two models represent the core "practice interview" feature.
One session contains multiple questions answered in sequence.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime, Enum, ForeignKey, Index, Integer, String, Text, func
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class InterviewSession(Base):
    """
    One practice interview session.

    A user starts a session (status=active), answers questions,
    and the session completes (status=completed) with a final score.

    WHY track score at session level AND per-submission?
      Session score = aggregate for the dashboard ("your DSA score: 72%")
      Submission score = granular for feedback ("you scored 45% on this question")
      Both are needed — don't collapse them into one.
    """
    __tablename__ = "interview_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )

    # ── Foreign key ────────────────────────────────────────────────────────────
    # WHY ondelete="CASCADE"?
    #   If the referenced user is deleted, Postgres automatically deletes
    #   all their sessions too. Without CASCADE, deleting a user with sessions
    #   raises a ForeignKeyViolation error — the DB protects referential integrity.
    #
    # WHY index=True on FK columns?
    #   The most common query pattern: "get all sessions for user X"
    #     SELECT * FROM interview_sessions WHERE user_id = ?
    #   Without an index on user_id: full table scan across ALL sessions.
    #   With an index: instant lookup. This is one of the most common
    #   performance mistakes beginners make.
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # The technical topic for this session (DSA, OS, DBMS, CN, OOP, System Design)
    topic: Mapped[str] = mapped_column(String(50), nullable=False)

    difficulty: Mapped[str] = mapped_column(
        Enum("easy", "medium", "hard", name="difficulty_enum"),
        nullable=False,
        server_default="medium",
    )

    # WHY Enum for status?
    #   Finite state machine: active → completed | abandoned
    #   Enum prevents invalid states like "done", "finished", "complete"
    status: Mapped[str] = mapped_column(
        Enum("active", "completed", "abandoned", name="session_status_enum"),
        nullable=False,
        server_default="active",
        index=True,  # "fetch all active sessions" is a common query
    )

    # Aggregate score 0-100, computed when session completes
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ── Relationships ──────────────────────────────────────────────────────────
    user: Mapped["User"] = relationship("User", back_populates="sessions")
    questions: Mapped[list["SessionQuestion"]] = relationship(
        "SessionQuestion",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="SessionQuestion.order_index",  # Always return in question order
    )

    __table_args__ = (
        # Composite index: "get all completed DSA sessions for user X"
        # This is a real query the analytics page will run constantly.
        Index("ix_sessions_user_topic_status", "user_id", "topic", "status"),
    )

    def __repr__(self) -> str:
        return f"<InterviewSession id={self.id} topic={self.topic} status={self.status}>"


class SessionQuestion(Base):
    """
    One question within an interview session.

    WHY store a snapshot instead of only a question-bank reference?
      The curated bank lives in code for this MVP. Persisting the text and ideal
      answer keeps old session reviews stable if curated wording changes later.
    """
    __tablename__ = "session_questions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("interview_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # WHY Text instead of String for question content?
    #   String(n) has a fixed max length. Interview questions can be long.
    #   Text is PostgreSQL's variable-length type — no practical limit.
    #   Use String for short, bounded values (email, name). Text for long content.
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    ideal_answer: Mapped[str] = mapped_column(Text, nullable=False)

    # Stable curated-bank metadata. Nullable keeps legacy session snapshots valid.
    question_bank_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)

    # Which broad topic and granular skill this question tests
    skill_topic: Mapped[str] = mapped_column(String(50), nullable=False)
    skill_tag: Mapped[str | None] = mapped_column(String(50), nullable=True)
    difficulty: Mapped[str | None] = mapped_column(String(10), nullable=True)

    # Display order within the session (1, 2, 3...)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)

    # ── Relationships ──────────────────────────────────────────────────────────
    session: Mapped["InterviewSession"] = relationship(
        "InterviewSession",
        back_populates="questions",
    )
    submissions: Mapped[list["Submission"]] = relationship(
        "Submission",
        back_populates="question",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<SessionQuestion id={self.id} topic={self.skill_topic}>"
