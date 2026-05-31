"""
ml/main.py — ML service with Groq-powered classification and feedback
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field

from evaluator.evaluator import get_evaluator
from classifier.skill_classifier import get_skill_classifier
from llm.feedback_generator import get_feedback_generator
from llm.groq_client import get_groq_client


# ── Schemas ────────────────────────────────────────────────────────────────────

class EvaluateRequest(BaseModel):
    candidate_answer: str = Field(..., min_length=1, max_length=5000)
    ideal_answer: str = Field(..., min_length=1, max_length=5000)
    topic: str = Field(default="General", max_length=50)
    question: str = Field(default="", max_length=1000)  # For LLM feedback context

class ClassifyRequest(BaseModel):
    question: str = Field(..., min_length=5, max_length=2000)

class ClassifyResponse(BaseModel):
    topic: str
    confidence: float
    reasoning: str
    model_used: str
    latency_ms: float

class FeedbackRequest(BaseModel):
    question: str
    ideal_answer: str
    candidate_answer: str
    similarity_score: float
    confidence_score: float
    keywords_matched: list[str]
    topic: str
    grade: str

class SessionSummaryRequest(BaseModel):
    topic: str
    questions: list[str]
    scores: list[float]
    overall_grade: str


# ── Lifespan ───────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("ML Service starting...")

    # Load TF-IDF classifier (fast, always works)
    classifier = get_skill_classifier()
    classifier._tfidf_classifier()   # Trigger training/loading
    print("TF-IDF classifier ready")

    # Check Groq availability
    groq = get_groq_client()
    if groq.is_available():
        print(f"Groq configured: {groq.model}")
    else:
        print("WARNING: GROQ_API_KEY not set — using TF-IDF fallback only")

    # Load sentence transformer (may fail in restricted environments)
    try:
        evaluator = get_evaluator()
        evaluator._load_model()
        print("Sentence Transformer ready")
    except Exception as e:
        print(f"WARNING: Sentence Transformer unavailable: {e}")
        print("Evaluation will use keyword-only scoring")

    yield
    print("ML Service shutting down.")


app = FastAPI(
    title="DevMentor AI — ML Service",
    version="2.0.0",
    lifespan=lifespan,
)


# ── Health ─────────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    groq = get_groq_client()
    evaluator = get_evaluator()
    return {
        "status": "healthy",
        "groq_available": groq.is_available(),
        "groq_model": groq.model if groq.is_available() else None,
        "sentence_transformer_loaded": evaluator._model is not None,
        "tfidf_ready": True,
    }


# ── Classification ─────────────────────────────────────────────────────────────
@app.post("/classify", response_model=ClassifyResponse)
async def classify_question(request: ClassifyRequest) -> ClassifyResponse:
    """
    Classify an interview question into one of 6 technical topics.
    Uses Groq LLM when available, TF-IDF as fallback.
    """
    result = get_skill_classifier().classify(request.question)
    return ClassifyResponse(
        topic=result.topic,
        confidence=result.confidence,
        reasoning=result.reasoning,
        model_used=result.model_used,
        latency_ms=result.latency_ms,
    )


# ── Evaluation ─────────────────────────────────────────────────────────────────
@app.post("/evaluate")
async def evaluate_answer(request: EvaluateRequest) -> dict:
    """
    Evaluate a candidate answer. Returns semantic scores + LLM feedback.
    """
    evaluator = get_evaluator()

    # Semantic scoring (Sentence Transformer)
    if evaluator._model is not None:
        result = evaluator.evaluate(
            candidate_answer=request.candidate_answer,
            ideal_answer=request.ideal_answer,
            topic=request.topic,
        )
        scores = {
            "similarity_score": result.similarity_score,
            "confidence_score": result.confidence_score,
            "final_score": result.final_score,
            "grade": result.grade,
            "keywords_matched": result.keywords_matched,
            "inference_time_ms": result.inference_time_ms,
        }
    else:
        # Degraded mode: keyword-only scoring when model unavailable
        from evaluator.evaluator import AnswerEvaluator
        dummy = AnswerEvaluator()
        confidence, keywords = dummy._confidence_score(request.candidate_answer, request.topic)
        scores = {
            "similarity_score": None,
            "confidence_score": round(confidence, 4),
            "final_score": round(confidence * 70, 1),  # Cap at 70 without semantic score
            "grade": "Fair" if confidence > 0.5 else "Needs Work",
            "keywords_matched": keywords,
            "inference_time_ms": 0.0,
        }

    # LLM feedback generation (Groq)
    feedback = get_feedback_generator().generate(
        question=request.question,
        ideal_answer=request.ideal_answer,
        candidate_answer=request.candidate_answer,
        similarity_score=scores["similarity_score"] or 0.0,
        confidence_score=scores["confidence_score"],
        keywords_matched=scores["keywords_matched"],
        topic=request.topic,
        grade=scores["grade"],
    )

    return {**scores, "feedback": feedback}


# ── LLM Feedback ───────────────────────────────────────────────────────────────
@app.post("/feedback")
async def generate_feedback(request: FeedbackRequest) -> dict:
    """Generate LLM coaching feedback for a pre-scored answer."""
    return get_feedback_generator().generate(
        question=request.question,
        ideal_answer=request.ideal_answer,
        candidate_answer=request.candidate_answer,
        similarity_score=request.similarity_score,
        confidence_score=request.confidence_score,
        keywords_matched=request.keywords_matched,
        topic=request.topic,
        grade=request.grade,
    )


@app.post("/feedback/session-summary")
async def session_summary(request: SessionSummaryRequest) -> dict:
    """Generate end-of-session coaching summary with study plan."""
    return get_feedback_generator().generate_session_summary(
        topic=request.topic,
        questions=request.questions,
        scores=request.scores,
        overall_grade=request.overall_grade,
    )


# ── Recommendation Engine endpoints ───────────────────────────────────────────

from recommender.engine import get_recommendation_engine


class RecommendationRequest(BaseModel):
    skill_scores: dict[str, float]   # {"DSA": 0.34, "OS": 0.71, ...}
    user_goal: str = Field(default="general interview preparation", max_length=200)


class RoadmapItemResponse(BaseModel):
    resource_id: str
    title: str
    url: str
    resource_type: str
    topic: str
    difficulty: str
    estimated_hours: float
    description: str
    priority: int
    why: str
    week: int
    prerequisite_for: list[str]


class RecommendationResponse(BaseModel):
    reasoning: str
    weak_topics: list[str]
    items: list[RoadmapItemResponse]
    generated_by: str
    latency_ms: float


@app.post("/recommend", response_model=RecommendationResponse)
async def recommend(request: RecommendationRequest) -> RecommendationResponse:
    """
    Generate a personalized learning roadmap from skill assessment scores.

    Input: dict of {topic: proficiency_score}
    Output: ordered list of learning resources with rationale

    The engine uses content-based filtering + Groq personalization.
    Falls back to pure algorithmic ranking if Groq is unavailable.
    """
    engine = get_recommendation_engine()
    roadmap = engine.generate(
        skill_scores=request.skill_scores,
        user_goal=request.user_goal,
    )

    return RecommendationResponse(
        reasoning=roadmap.reasoning,
        weak_topics=roadmap.weak_topics,
        items=[
            RoadmapItemResponse(
                resource_id=item.resource.id,
                title=item.resource.title,
                url=item.resource.url,
                resource_type=item.resource.resource_type,
                topic=item.resource.topic,
                difficulty=item.resource.difficulty,
                estimated_hours=item.resource.estimated_hours,
                description=item.resource.description,
                priority=item.priority,
                why=item.why,
                week=item.week,
                prerequisite_for=item.prerequisite_for,
            )
            for item in roadmap.items
        ],
        generated_by=roadmap.generated_by,
        latency_ms=roadmap.latency_ms,
    )


@app.get("/catalogue/stats")
async def catalogue_stats():
    """Admin endpoint — shows resource catalogue coverage."""
    from recommender.catalogue import get_catalogue_stats
    return get_catalogue_stats()
