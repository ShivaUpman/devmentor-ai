"""
tests/test_interview_service.py — Interview service tests

Tests the complete interview flow:
  create_session → get_questions → submit_answer → complete_session

All ML calls are mocked — these are unit tests of the service logic,
not integration tests of the ML model.

WHY test the service and not the endpoint?
  Service tests don't require a running HTTP server, ASGI transport, or
  full request/response cycle. They test business logic in isolation.
  Endpoint tests (integration) would use httpx.AsyncClient with app —
  added in a separate integration test file.
"""

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.services.interview_service import (
    InterviewService,
    get_questions_for_session,
    QUESTION_BANK,
)
from app.services.question_bank import adjust_difficulty, select_adaptive_question
from app.models.user import User


# ── Question bank tests ───────────────────────────────────────────────────────

class TestQuestionBank:
    def test_all_topics_have_questions(self):
        for topic in ["DSA", "OS", "DBMS", "CN", "OOP", "System Design"]:
            assert topic in QUESTION_BANK, f"Missing topic: {topic}"
            for difficulty in ["easy", "medium", "hard"]:
                bank = QUESTION_BANK[topic].get(difficulty, [])
                assert len(bank) > 0, f"Missing {difficulty} questions for {topic}"

    def test_each_question_has_answer(self):
        for topic, difficulties in QUESTION_BANK.items():
            for difficulty, questions in difficulties.items():
                for q in questions:
                    assert "q" in q, f"{topic}/{difficulty}: question missing 'q' key"
                    assert "a" in q, f"{topic}/{difficulty}: question missing 'a' key"
                    assert q["id"], f"{topic}/{difficulty}: question missing stable ID"
                    assert q["skill"], f"{topic}/{difficulty}: question missing skill tag"
                    assert q["difficulty"] == difficulty
                    assert len(q["q"]) > 20, f"{topic}/{difficulty}: question too short"
                    assert len(q["a"]) > 50, f"{topic}/{difficulty}: answer too short"

    def test_get_questions_returns_correct_count(self):
        questions = get_questions_for_session("DSA", "medium", count=2)
        assert len(questions) <= 2

    def test_get_questions_falls_back_to_medium(self):
        """If difficulty not found, should fall back gracefully."""
        questions = get_questions_for_session("DSA", "nonexistent_difficulty")
        assert len(questions) > 0

    def test_get_questions_unknown_topic_returns_empty(self):
        questions = get_questions_for_session("Quantum Computing", "easy")
        assert questions == []

    def test_question_bank_has_minimum_coverage(self):
        """Verify minimum question count across all topics."""
        total = sum(
            len(qs)
            for topic_data in QUESTION_BANK.values()
            for qs in topic_data.values()
        )
        assert total >= 270, f"Question bank too small: {total} questions"

    def test_each_bucket_has_at_least_15_questions(self):
        for topic, difficulties in QUESTION_BANK.items():
            for difficulty, questions in difficulties.items():
                assert len(questions) >= 15, f"{topic}/{difficulty} needs more questions"

    def test_question_ids_are_unique(self):
        ids = [
            question["id"]
            for difficulties in QUESTION_BANK.values()
            for questions in difficulties.values()
            for question in questions
        ]
        assert len(ids) == len(set(ids))


class TestAdaptiveSelection:
    def test_strong_answer_increases_difficulty(self):
        assert adjust_difficulty("medium", 0.85) == "hard"
        assert adjust_difficulty("hard", 0.95) == "hard"

    def test_weak_answer_decreases_difficulty(self):
        assert adjust_difficulty("medium", 0.40) == "easy"
        assert adjust_difficulty("easy", 0.20) == "easy"

    def test_neutral_answer_keeps_difficulty(self):
        assert adjust_difficulty("medium", 0.65) == "medium"

    def test_selector_avoids_attempted_questions(self):
        first = select_adaptive_question(QUESTION_BANK, "DSA", "medium", set(), {})
        selected = select_adaptive_question(QUESTION_BANK, "DSA", "medium", {first["id"]}, {})
        assert selected["id"] != first["id"]

    def test_selector_prioritizes_weakest_skill(self):
        selected = select_adaptive_question(
            QUESTION_BANK,
            "DSA",
            "medium",
            set(),
            {
                "complexity": 0.9,
                "linear-structures": 0.8,
                "trees-graphs": 0.2,
                "hashing": 0.7,
                "problem-solving": 0.6,
            },
        )
        assert selected["skill"] == "trees-graphs"

    def test_selector_falls_back_when_target_bucket_is_exhausted(self):
        attempted = {
            question["id"]
            for question in QUESTION_BANK["DSA"]["medium"]
        }
        selected = select_adaptive_question(QUESTION_BANK, "DSA", "medium", attempted, {})
        assert selected is not None
        assert selected["difficulty"] in {"easy", "hard"}

    def test_selector_returns_none_when_topic_is_exhausted(self):
        attempted = {
            question["id"]
            for questions in QUESTION_BANK["DSA"].values()
            for question in questions
        }
        assert select_adaptive_question(QUESTION_BANK, "DSA", "medium", attempted, {}) is None


# ── InterviewService tests ────────────────────────────────────────────────────

class TestInterviewService:
    """Tests for the InterviewService class using mocked DB and ML client."""

    @pytest.fixture
    def mock_user(self):
        user = MagicMock(spec=User)
        user.id = uuid.uuid4()
        user.email = "test@example.com"
        user.full_name = "Test User"
        return user

    @pytest.fixture
    def mock_db(self):
        """Mock AsyncSession that simulates basic ORM operations."""
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        # Mock execute to return empty results by default
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=mock_result)
        return db

    @pytest.fixture
    def mock_ml_client(self):
        """Mock ML client that returns realistic evaluation scores."""
        ml = AsyncMock()
        ml.evaluate_answer = AsyncMock(return_value={
            "similarity_score": 0.78,
            "confidence_score": 0.65,
            "final_score": 73.6,
            "grade": "Good",
            "feedback": {
                "assessment": "Good answer covering the main concepts.",
                "strengths": "Correctly identified the key mechanisms.",
                "improvements": "Could mention edge cases more explicitly.",
                "hint": "What happens at the boundary conditions?",
            },
            "keywords_matched": ["binary search", "O(log n)"],
            "inference_time_ms": 45.2,
        })
        return ml

    @pytest.mark.asyncio
    async def test_create_session_adds_to_db(self, mock_db, mock_ml_client, mock_user):
        """Creating a session should add the session and questions to the DB."""
        from app.schemas.interview import SessionCreate

        service = InterviewService(db=mock_db, ml_client=mock_ml_client)
        data = SessionCreate(topic="DSA", difficulty="medium")

        session = await service.create_session(mock_user, data)

        # Session should be added to DB
        assert mock_db.add.called
        assert mock_db.flush.called
        assert session.topic == "DSA"
        assert session.difficulty == "medium"
        assert session.status == "active"
        assert session.user_id == mock_user.id

    @pytest.mark.asyncio
    async def test_create_session_sets_correct_topic(self, mock_db, mock_ml_client, mock_user):
        from app.schemas.interview import SessionCreate
        service = InterviewService(db=mock_db, ml_client=mock_ml_client)

        for topic in ["DSA", "OS", "DBMS", "CN", "OOP", "System Design"]:
            session = await service.create_session(mock_user, SessionCreate(topic=topic, difficulty="easy"))
            assert session.topic == topic

    @pytest.mark.asyncio
    async def test_next_question_persists_adaptive_metadata(self, mock_db, mock_user):
        from app.models.session import InterviewSession, SessionQuestion

        session = MagicMock(spec=InterviewSession)
        session.id = uuid.uuid4()
        session.topic = "DSA"
        session.difficulty = "medium"
        session.status = "active"

        service = InterviewService(db=mock_db, ml_client=AsyncMock())
        service.get_session = AsyncMock(return_value=session)
        service._get_unanswered_question = AsyncMock(return_value=None)
        service._get_latest_session_score = AsyncMock(return_value=0.85)
        service._get_attempted_question_ids = AsyncMock(return_value=set())
        service._get_skill_scores = AsyncMock(return_value={"complexity": 0.1})
        service.get_questions = AsyncMock(return_value=[])

        question = await service.next_question(session.id, mock_user.id)

        assert isinstance(question, SessionQuestion)
        assert question.question_bank_id
        assert question.skill_tag
        assert question.difficulty == "hard"
        assert question.order_index == 1
        assert session.difficulty == "hard"

    @pytest.mark.asyncio
    async def test_next_question_returns_existing_unanswered_question(self, mock_db, mock_user):
        from app.models.session import InterviewSession, SessionQuestion

        session = MagicMock(spec=InterviewSession)
        session.status = "active"
        existing = MagicMock(spec=SessionQuestion)

        service = InterviewService(db=mock_db, ml_client=AsyncMock())
        service.get_session = AsyncMock(return_value=session)
        service._get_unanswered_question = AsyncMock(return_value=existing)

        assert await service.next_question(uuid.uuid4(), mock_user.id) is existing

    @pytest.mark.asyncio
    async def test_submit_answer_saves_before_scoring(self, mock_db, mock_user):
        """Answer must be persisted BEFORE ML scoring is attempted."""
        from app.models.session import SessionQuestion

        mock_question = MagicMock(spec=SessionQuestion)
        mock_question.id = uuid.uuid4()
        mock_question.question_text = "What is binary search?"
        mock_question.ideal_answer = "Binary search is O(log n)..."
        mock_question.skill_topic = "DSA"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_question
        mock_db.execute = AsyncMock(return_value=mock_result)

        ml = AsyncMock()
        ml.evaluate_answer = AsyncMock(return_value={
            "similarity_score": 0.7,
            "confidence_score": 0.6,
            "final_score": 67.0,
            "grade": "Good",
            "feedback": {"assessment": "Good answer"},
            "keywords_matched": [],
        })

        service = InterviewService(db=mock_db, ml_client=ml)
        # Patch _update_skill_assessment so it doesn't make extra DB calls
        service._update_skill_assessment = AsyncMock()

        submission = await service.submit_answer(
            question_id=mock_question.id,
            user_id=mock_user.id,
            answer_text="Binary search divides the search space in half each time.",
        )

        assert mock_db.add.called
        assert submission.answer_text == "Binary search divides the search space in half each time."
        assert submission.similarity_score == 0.7
        # _update_skill_assessment was called with correct args
        service._update_skill_assessment.assert_called_once_with(
            user_id=mock_user.id, topic="DSA", new_score=pytest.approx(0.676, rel=0.1)
        )

    @pytest.mark.asyncio
    async def test_submit_answer_graceful_degradation_when_ml_fails(self, mock_db, mock_user):
        """If ML fails, answer is still saved — scores are null, no exception raised."""
        from app.models.session import SessionQuestion
        from app.services.ml_client import MLServiceError

        mock_question = MagicMock(spec=SessionQuestion)
        mock_question.id = uuid.uuid4()
        mock_question.question_text = "Test question"
        mock_question.ideal_answer = "Test ideal answer"
        mock_question.skill_topic = "DSA"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_question
        mock_db.execute = AsyncMock(return_value=mock_result)

        # ML service unavailable
        failing_ml = AsyncMock()
        failing_ml.evaluate_answer = AsyncMock(side_effect=MLServiceError("timeout"))

        service = InterviewService(db=mock_db, ml_client=failing_ml)
        submission = await service.submit_answer(
            question_id=mock_question.id,
            user_id=mock_user.id,
            answer_text="My answer here, at least ten characters long.",
        )

        # Answer saved
        assert submission.answer_text is not None
        # Scores are null (ML failed gracefully)
        assert submission.similarity_score is None
        assert submission.confidence_score is None

    @pytest.mark.asyncio
    async def test_submit_answer_question_not_found_raises_404(self, mock_db, mock_user):
        """Submitting to a question that doesn't belong to the user raises 404."""
        from fastapi import HTTPException

        # Question not found (returns None)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        service = InterviewService(db=mock_db, ml_client=AsyncMock())
        with pytest.raises(HTTPException) as exc:
            await service.submit_answer(
                question_id=uuid.uuid4(),
                user_id=mock_user.id,
                answer_text="Answer text long enough to pass validation checks.",
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_complete_session_sets_status(self, mock_db, mock_user):
        """Completing a session sets status=completed and computes score."""
        from app.models.session import InterviewSession
        from app.models.submission import Submission

        session_id = uuid.uuid4()

        mock_session = MagicMock(spec=InterviewSession)
        mock_session.id = session_id
        mock_session.user_id = mock_user.id
        mock_session.status = "active"
        mock_session.score = None

        mock_submission1 = MagicMock()
        mock_submission1.similarity_score = 0.8

        mock_submission2 = MagicMock()
        mock_submission2.similarity_score = 0.6

        # First call: get session; second call: get submissions
        call_count = 0
        async def mock_execute(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = mock_session
            elif call_count == 2:
                result.scalars.return_value.all.return_value = [mock_submission1, mock_submission2]
            else:
                result.scalar_one_or_none.return_value = None
                result.scalars.return_value.all.return_value = []
            return result

        mock_db.execute = mock_execute

        service = InterviewService(db=mock_db, ml_client=AsyncMock())
        completed = await service.complete_session(session_id, mock_user.id)

        assert completed.status == "completed"
        assert completed.ended_at is not None
        # Score = avg(0.8, 0.6) * 100 = 70
        assert completed.score == 70

    @pytest.mark.asyncio
    async def test_complete_already_completed_session_raises_400(self, mock_db, mock_user):
        """Can't complete a session that's already completed."""
        from fastapi import HTTPException
        from app.models.session import InterviewSession

        mock_session = MagicMock(spec=InterviewSession)
        mock_session.id = uuid.uuid4()
        mock_session.user_id = mock_user.id
        mock_session.status = "completed"  # Already done

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_session
        mock_db.execute = AsyncMock(return_value=mock_result)

        service = InterviewService(db=mock_db, ml_client=AsyncMock())
        with pytest.raises(HTTPException) as exc:
            await service.complete_session(mock_session.id, mock_user.id)
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_skill_assessment_upsert_creates_on_first_attempt(self, mock_db, mock_user):
        """First assessment for a topic creates a new SkillAssessment row."""
        from app.models.submission import SkillAssessment

        # No existing assessment
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        service = InterviewService(db=mock_db, ml_client=AsyncMock())
        await service._update_skill_assessment(
            user_id=mock_user.id,
            topic="DSA",
            new_score=0.75,
        )

        # Should have added a new assessment
        mock_db.add.assert_called_once()
        added_obj = mock_db.add.call_args[0][0]
        assert isinstance(added_obj, SkillAssessment)
        assert added_obj.proficiency_score == 0.75
        assert added_obj.attempts == 1

    @pytest.mark.asyncio
    async def test_skill_assessment_uses_exponential_moving_average(self, mock_db, mock_user):
        """Subsequent assessments use EMA (alpha=0.3) not simple average."""
        from app.models.submission import SkillAssessment

        # Existing assessment
        existing = MagicMock(spec=SkillAssessment)
        existing.proficiency_score = 0.5
        existing.attempts = 5

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_db.execute = AsyncMock(return_value=mock_result)

        service = InterviewService(db=mock_db, ml_client=AsyncMock())
        await service._update_skill_assessment(
            user_id=mock_user.id,
            topic="DSA",
            new_score=0.9,
        )

        # EMA: 0.7 * 0.5 + 0.3 * 0.9 = 0.35 + 0.27 = 0.62
        expected = 0.7 * 0.5 + 0.3 * 0.9
        assert abs(existing.proficiency_score - expected) < 1e-9
        assert existing.attempts == 6


# ── ML Client tests ───────────────────────────────────────────────────────────

class TestMLClientFixed:
    """Verify the ml_client.py fix — all methods inside the class."""

    def test_ml_client_has_all_methods(self):
        """All methods must be attributes of the class, not module-level."""
        from app.services.ml_client import MLClient
        client = MLClient(base_url="http://test:8001")

        required_methods = [
            'evaluate_answer',
            'evaluate_batch',
            'classify_question',
            'recommend',
            'generate_feedback',
            'session_summary',
            'health_check',
            'close',
        ]
        for method_name in required_methods:
            assert hasattr(client, method_name), f"MLClient missing method: {method_name}"
            assert callable(getattr(client, method_name)), f"{method_name} is not callable"

    def test_recommend_is_instance_method_not_module_level(self):
        """The original bug: recommend was appended outside the class."""
        from app.services import ml_client as ml_module
        from app.services.ml_client import MLClient

        # Should NOT be a module-level function
        assert not hasattr(ml_module, 'recommend'), \
            "recommend() leaked to module level — it must be inside MLClient class"

        # SHOULD be an instance method
        client = MLClient(base_url="http://test")
        assert hasattr(client, 'recommend')

    @pytest.mark.asyncio
    async def test_post_handles_timeout(self):
        """_post() must raise MLServiceError on timeout."""
        import httpx
        from app.services.ml_client import MLClient, MLServiceError

        client = MLClient(base_url="http://test:9999")
        # Inject mock client directly to bypass lazy init
        mock_inner = AsyncMock()
        mock_inner.is_closed = False
        mock_inner.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
        client._client = mock_inner

        with pytest.raises(MLServiceError):
            await client._post("/evaluate", {"test": "data"})

    @pytest.mark.asyncio
    async def test_post_handles_connection_error(self):
        """_post() must raise MLServiceError on connect failure."""
        import httpx
        from app.services.ml_client import MLClient, MLServiceError

        client = MLClient(base_url="http://test:9999")
        client._client = AsyncMock()
        client._client.is_closed = False
        client._client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))

        with pytest.raises(MLServiceError, match="unreachable"):
            await client._post("/evaluate", {"test": "data"})
