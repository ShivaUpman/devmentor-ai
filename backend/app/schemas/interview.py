"""schemas/interview.py — Pydantic schemas for Interview Sessions"""

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class SessionCreate(BaseModel):
    topic: str = Field(..., pattern="^(DSA|OS|DBMS|CN|OOP|System Design)$")
    difficulty: str = Field(default="medium", pattern="^(easy|medium|hard)$")


class QuestionResponse(BaseModel):
    """
    Public question representation.
    NOTE: ideal_answer is deliberately excluded — never sent to the client.
    The ideal answer lives in the DB and is fetched server-side for ML scoring.
    """
    id: uuid.UUID
    question_text: str
    skill_topic: str
    skill_tag: Optional[str] = None
    difficulty: Optional[str] = None
    order_index: int
    model_config = {"from_attributes": True}


class SubmissionCreate(BaseModel):
    answer_text: str = Field(..., min_length=10, max_length=5000)


class SubmissionResponse(BaseModel):
    id: uuid.UUID
    answer_text: str
    similarity_score: Optional[float] = None
    confidence_score: Optional[float] = None
    ai_feedback: Optional[str] = None
    submitted_at: datetime
    model_config = {"from_attributes": True}


class SessionResponse(BaseModel):
    id: uuid.UUID
    topic: str
    difficulty: str
    status: str
    score: Optional[int] = None
    started_at: datetime
    ended_at: Optional[datetime] = None
    model_config = {"from_attributes": True}


class SessionResultItem(BaseModel):
    """One Q&A pair in a session results review."""
    question: str
    skill_topic: str
    order_index: int
    answer_text: Optional[str] = None
    similarity_score: Optional[float] = None
    confidence_score: Optional[float] = None
    ai_feedback: Optional[dict] = None
    submitted_at: Optional[str] = None


class SessionResultsResponse(BaseModel):
    session_id: str
    topic: str
    difficulty: str
    score: Optional[int] = None
    status: str
    results: list[SessionResultItem]
