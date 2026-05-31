"""
api/v1/endpoints/interview.py — Interview session HTTP endpoints

REST design:
  POST   /interview/                           — start a new session
  GET    /interview/                           — list user's sessions
  GET    /interview/{session_id}               — get session details
  GET    /interview/{session_id}/questions     — get questions for session
  POST   /interview/questions/{question_id}/submit  — submit an answer
  POST   /interview/{session_id}/complete      — mark session complete
  POST   /interview/{session_id}/abandon       — mark session abandoned
  GET    /interview/{session_id}/results       — full session review

WHY separate complete and abandon?
  Different end states have different downstream effects:
    complete → computes aggregate score, updates skill assessments, invalidates roadmap
    abandon  → marks as abandoned, no score computed
  Keeping them separate makes the state machine explicit.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.core.logging import logger
from app.db.session import get_db
from app.models.user import User
from app.schemas.interview import (
    QuestionResponse,
    SessionCreate,
    SessionResponse,
    SubmissionCreate,
    SubmissionResponse,
)
from app.services.cache_service import CacheService
from app.services.interview_service import InterviewService

router = APIRouter()

CurrentUser = Annotated[User, Depends(get_current_user)]


def get_interview_service(
    db: AsyncSession = Depends(get_db),
) -> InterviewService:
    """Build the service with optional Redis cache injection."""
    try:
        from app.db.redis import get_redis_dep
        # Cache injected in endpoints that use it
    except Exception:
        pass
    return InterviewService(db=db)


@router.post(
    "/",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start a new interview session",
)
async def start_session(
    data: SessionCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> SessionResponse:
    """
    Start a new practice interview session.

    Creates the session, loads questions from the bank for the
    chosen topic and difficulty, and returns the session metadata.
    The questions are fetched separately via GET /{session_id}/questions.
    """
    service = InterviewService(db=db)
    session = await service.create_session(current_user, data)
    return SessionResponse.model_validate(session)


@router.get(
    "/",
    response_model=list[SessionResponse],
    summary="List all sessions for the current user",
)
async def list_sessions(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> list[SessionResponse]:
    """Return all interview sessions for the authenticated user, newest first."""
    service = InterviewService(db=db)
    sessions = await service.get_sessions(current_user.id)
    return [SessionResponse.model_validate(s) for s in sessions]


@router.get(
    "/{session_id}",
    response_model=SessionResponse,
    summary="Get a specific session",
)
async def get_session(
    session_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> SessionResponse:
    """Fetch details of one session. Returns 404 if not found or not owned by user."""
    service = InterviewService(db=db)
    session = await service.get_session(session_id, current_user.id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionResponse.model_validate(session)


@router.get(
    "/{session_id}/questions",
    response_model=list[QuestionResponse],
    summary="Get questions for a session",
)
async def get_questions(
    session_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> list[QuestionResponse]:
    """
    Return all questions for a session in order.

    The ideal answer is NOT returned here — only question_text and metadata.
    This prevents the frontend from displaying the answer before the user responds.
    The ideal answer is stored in the DB and used by the ML service for scoring.
    """
    service = InterviewService(db=db)
    # Verify session ownership
    session = await service.get_session(session_id, current_user.id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    questions = await service.get_questions(session_id)
    return [QuestionResponse.model_validate(q) for q in questions]


@router.post(
    "/{session_id}/questions/next",
    response_model=QuestionResponse,
    responses={204: {"description": "No unused questions remain"}},
    summary="Issue the next adaptive question",
)
async def get_next_question(
    session_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> QuestionResponse | Response:
    """Return one adaptive question, or 204 when the curated bank is exhausted."""
    service = InterviewService(db=db)
    question = await service.next_question(session_id, current_user.id)
    if question is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    return QuestionResponse.model_validate(question)


@router.post(
    "/questions/{question_id}/submit",
    response_model=SubmissionResponse,
    summary="Submit an answer to a question",
)
async def submit_answer(
    question_id: uuid.UUID,
    data: SubmissionCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> SubmissionResponse:
    """
    Submit the user's answer to a question.

    The answer is saved immediately, then scored by the ML service.
    If the ML service is unavailable, scores are null — the submission
    is still saved and can be scored later.

    Returns the submission with scores and AI feedback (may be null
    if ML service is temporarily unavailable).
    """
    service = InterviewService(db=db)
    submission = await service.submit_answer(
        question_id=question_id,
        user_id=current_user.id,
        answer_text=data.answer_text,
    )
    return SubmissionResponse.model_validate(submission)


@router.post(
    "/{session_id}/complete",
    response_model=SessionResponse,
    summary="Mark a session as completed",
)
async def complete_session(
    session_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> SessionResponse:
    """
    Complete an active session.

    Computes the aggregate score from all answered questions,
    marks the session as completed, and invalidates the skill
    assessment cache so the dashboard shows fresh data.
    """
    service = InterviewService(db=db)
    session = await service.complete_session(session_id, current_user.id)
    return SessionResponse.model_validate(session)


@router.post(
    "/{session_id}/abandon",
    response_model=SessionResponse,
    summary="Abandon an active session",
)
async def abandon_session(
    session_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> SessionResponse:
    """Mark a session as abandoned — no score computed."""
    service = InterviewService(db=db)
    session = await service.abandon_session(session_id, current_user.id)
    return SessionResponse.model_validate(session)


@router.get(
    "/{session_id}/results",
    summary="Get full session results with all Q&A and scores",
)
async def get_session_results(
    session_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Return the complete session review — all questions, user answers,
    scores, and AI feedback. Used by the results page.
    """
    service = InterviewService(db=db)
    results = await service.get_submissions_for_session(session_id, current_user.id)
    session = await service.get_session(session_id, current_user.id)
    return {
        "session_id": str(session_id),
        "topic": session.topic if session else None,
        "difficulty": session.difficulty if session else None,
        "score": session.score if session else None,
        "status": session.status if session else None,
        "results": results,
    }
