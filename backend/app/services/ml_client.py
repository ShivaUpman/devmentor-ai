"""
services/ml_client.py — Async HTTP client for the ML microservice

All ML operations (evaluate, classify, recommend, feedback) route through
this single client. It manages connection pooling, timeouts, and graceful
degradation when the ML service is unavailable.
"""

from typing import Optional

import httpx

from app.core.config import settings


class MLServiceError(Exception):
    """Raised when the ML service returns an error or is unreachable."""
    pass


class MLClient:
    """
    Async HTTP client for the ML service with connection pooling.
    Instantiated once as a module-level singleton — avoids TCP overhead.
    """

    def __init__(self, base_url: Optional[str] = None, timeout: float = 15.0):
        self.base_url = base_url or settings.ML_SERVICE_URL
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(connect=5.0, read=self.timeout, write=5.0, pool=2.0),
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            )
        return self._client

    async def _post(self, path: str, payload: dict) -> dict:
        """Core POST with unified error handling for all ML calls."""
        client = await self._get_client()
        try:
            response = await client.post(path, json=payload)
            response.raise_for_status()
            return response.json()
        except httpx.TimeoutException:
            raise MLServiceError(f"ML service timed out after {self.timeout}s.")
        except httpx.ConnectError:
            raise MLServiceError("ML service unreachable.")
        except httpx.HTTPStatusError as e:
            raise MLServiceError(f"ML service error {e.response.status_code}: {e.response.text[:200]}")

    async def evaluate_answer(
        self,
        candidate_answer: str,
        ideal_answer: str,
        topic: str = "General",
        question: str = "",
    ) -> dict:
        """Evaluate one answer — returns scores + LLM feedback."""
        return await self._post("/evaluate", {
            "candidate_answer": candidate_answer,
            "ideal_answer": ideal_answer,
            "topic": topic,
            "question": question,
        })

    async def evaluate_batch(
        self,
        pairs: list[tuple[str, str]],
        topics: Optional[list[str]] = None,
    ) -> list[dict]:
        """Evaluate multiple answer pairs in one model forward pass."""
        return await self._post("/evaluate/batch", {"pairs": pairs, "topics": topics})

    async def classify_question(self, question: str) -> dict:
        """Classify a question into DSA/OS/DBMS/CN/OOP/System Design."""
        return await self._post("/classify", {"question": question})

    async def recommend(
        self,
        skill_scores: dict[str, float],
        user_goal: str = "general interview preparation",
    ) -> dict:
        """Generate personalized roadmap from skill scores."""
        return await self._post("/recommend", {"skill_scores": skill_scores, "user_goal": user_goal})

    async def generate_feedback(
        self,
        question: str,
        ideal_answer: str,
        candidate_answer: str,
        similarity_score: float,
        confidence_score: float,
        keywords_matched: list[str],
        topic: str,
        grade: str,
    ) -> dict:
        """Generate LLM coaching feedback for a scored answer."""
        return await self._post("/feedback", {
            "question": question,
            "ideal_answer": ideal_answer,
            "candidate_answer": candidate_answer,
            "similarity_score": similarity_score,
            "confidence_score": confidence_score,
            "keywords_matched": keywords_matched,
            "topic": topic,
            "grade": grade,
        })

    async def session_summary(
        self,
        topic: str,
        questions: list[str],
        scores: list[float],
        overall_grade: str,
    ) -> dict:
        """Generate end-of-session coaching summary with study plan."""
        return await self._post("/feedback/session-summary", {
            "topic": topic,
            "questions": questions,
            "scores": scores,
            "overall_grade": overall_grade,
        })

    async def health_check(self) -> dict:
        """Check ML service health — used by readiness probe."""
        client = await self._get_client()
        try:
            response = await client.get("/health", timeout=3.0)
            return response.json()
        except Exception:
            return {"status": "unreachable", "model_loaded": False}

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()


_ml_client: Optional[MLClient] = None


def get_ml_client() -> MLClient:
    global _ml_client
    if _ml_client is None:
        _ml_client = MLClient()
    return _ml_client
