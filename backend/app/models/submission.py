"""
models/submission.py — Submission, SkillAssessment, and RoadmapItem models

These three models form the "intelligence layer":
  Submission: raw answer + ML scores
  SkillAssessment: aggregated proficiency per topic per user
  RoadmapItem: personalized learning resources
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Index,
    Integer, String, Text, func
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class Submission(Base):
    """
    A user's answer to one interview question, with ML-computed scores.

    WHY store both similarity_score AND confidence_score?
      similarity_score: cosine similarity between user answer and ideal answer.
        Measures WHAT was said — content match.
      confidence_score: computed from response length, keyword density, structure.
        Measures HOW it was said — communication quality.

      Final score = weighted combination of both.
      This gives fairer evaluation: a short but precise answer scores differently
      from a long rambling answer that happens to contain the right words.
    """
    __tablename__ = "submissions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )

    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("session_questions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    answer_text: Mapped[str] = mapped_column(Text, nullable=False)

    # ML-computed scores — nullable because scoring is async (happens after submit)
    # WHY Float and not Integer?
    #   Cosine similarity is a continuous value in [0.0, 1.0].
    #   Storing as integer (e.g. 0-100) loses precision.
    #   We store raw float, multiply by 100 only for display.
    similarity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # AI-generated feedback text — can be long
    ai_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)

    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # ── Relationship ────────────────────────────────────────────────────────────
    question: Mapped["SessionQuestion"] = relationship(
        "SessionQuestion",
        back_populates="submissions",
    )

    def __repr__(self) -> str:
        return f"<Submission id={self.id} score={self.similarity_score}>"


class SkillAssessment(Base):
    """
    Aggregated skill proficiency for a user per topic.

    WHY a separate table and not just averaging submissions on the fly?
      Materialized aggregation — pre-computing the average avoids an expensive
      GROUP BY across all submissions every time the dashboard loads.

      This is a classic read-optimization: accept a slight write overhead
      (update this row after every submission) to make reads fast.

      Interview question: "What is a materialized view? When would you use one?"
      SkillAssessment is essentially a manually-maintained materialized view.
    """
    __tablename__ = "skill_assessments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    # One of: DSA, OS, DBMS, CN, OOP, System Design
    skill_topic: Mapped[str] = mapped_column(String(50), nullable=False)

    # Running average, updated after each submission in this topic
    proficiency_score: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        server_default="0.0",
    )

    # Number of times this topic has been assessed — used for weighted averaging
    attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
    )

    last_assessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # ── Relationship ────────────────────────────────────────────────────────────
    user: Mapped["User"] = relationship("User", back_populates="skill_assessments")

    __table_args__ = (
        # WHY a unique constraint on (user_id, skill_topic)?
        #   Each user has exactly ONE assessment row per topic.
        #   We UPSERT into this row (INSERT or UPDATE if exists).
        #   The unique constraint enforces this at the DB level — no duplicates.
        #
        # This is the UPSERT pattern:
        #   INSERT INTO skill_assessments ... ON CONFLICT (user_id, skill_topic)
        #   DO UPDATE SET proficiency_score = ...
        Index(
            "ix_skill_assessments_user_topic",
            "user_id",
            "skill_topic",
            unique=True,  # Enforces one row per (user, topic) pair
        ),
    )

    def __repr__(self) -> str:
        return f"<SkillAssessment user={self.user_id} topic={self.skill_topic} score={self.proficiency_score}>"


class RoadmapItem(Base):
    """
    One learning resource in a user's personalized roadmap.

    The recommendation engine (ML Module 3) populates this table
    by taking the user's weakest skills and selecting appropriate resources.

    WHY store resource_url here and not just generate it on-the-fly?
      Caching the recommendation prevents:
        1. Re-running the ML model on every page load (expensive)
        2. Different recommendations appearing on every visit (bad UX)
      The roadmap is stable and updated only when skill scores change significantly.
    """
    __tablename__ = "roadmap_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    skill_topic: Mapped[str] = mapped_column(String(50), nullable=False)
    resource_title: Mapped[str] = mapped_column(String(255), nullable=False)
    resource_url: Mapped[str] = mapped_column(String(512), nullable=False)

    # article | video | course | book | practice
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # Lower number = higher priority (1 = most urgent to learn)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")

    completed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="false",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # ── Relationship ────────────────────────────────────────────────────────────
    user: Mapped["User"] = relationship("User", back_populates="roadmap_items")

    __table_args__ = (
        # Fetch user's roadmap ordered by priority — this index makes it instant
        Index("ix_roadmap_user_priority", "user_id", "priority"),
    )

    def __repr__(self) -> str:
        return f"<RoadmapItem user={self.user_id} topic={self.skill_topic} priority={self.priority}>"
