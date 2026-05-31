"""
ml/classifier/skill_classifier.py — Orchestrates Groq + TF-IDF classification

This is the main entry point for question classification.
It implements the circuit-breaker pattern: try Groq first,
fall back to TF-IDF if Groq is unavailable or returns low confidence.
"""

import time
from dataclasses import dataclass

from classifier.tfidf_classifier import TFIDFClassifier, get_tfidf_classifier, TOPICS
from llm.groq_client import GroqClient, GroqClientError, get_groq_client

# Confidence threshold below which we supplement TF-IDF with Groq
TFIDF_CONFIDENCE_THRESHOLD = 0.70

CLASSIFICATION_SYSTEM_PROMPT = """You are an expert technical interviewer. 
Your task is to classify interview questions into exactly one of these topics:
DSA, OS, DBMS, CN, OOP, System Design

Rules:
- DSA: Data structures, algorithms, complexity, sorting, graphs, trees, dynamic programming
- OS: Operating systems, processes, threads, memory, scheduling, deadlock, synchronization  
- DBMS: Databases, SQL, transactions, indexing, normalization, ACID, NoSQL
- CN: Computer networks, TCP/IP, HTTP, DNS, protocols, routing, sockets
- OOP: Object-oriented design, classes, inheritance, design patterns, SOLID
- System Design: Distributed systems, scalability, architecture, CAP theorem, caching at scale

Respond ONLY with valid JSON in exactly this format:
{
  "topic": "OS",
  "confidence": 0.97,
  "reasoning": "The question asks about mutex vs semaphore — synchronization primitives in OS"
}"""


@dataclass
class ClassificationResult:
    topic: str
    confidence: float
    reasoning: str
    model_used: str          # "groq" | "tfidf" | "groq+tfidf"
    latency_ms: float


class SkillClassifier:
    """
    Orchestrates LLM + classical ML for robust question classification.

    Strategy:
      1. If Groq is available AND question is ambiguous → use Groq (high accuracy)
      2. If TF-IDF is confident (>70%) → use TF-IDF (fast, free, offline)
      3. If Groq is unavailable → always use TF-IDF (circuit breaker)
      4. When in doubt → Groq (it's free and accurate)

    WHY this priority order?
      TF-IDF is instant (~1ms) and free — use it when confident.
      Groq is slower (~200ms) but more accurate — use it for ambiguous questions.
      This balances latency, accuracy, and API quota consumption.
    """

    def __init__(
        self,
        groq_client: GroqClient = None,
        tfidf: TFIDFClassifier = None,
    ):
        self._groq = groq_client
        self._tfidf = tfidf

    def _groq_client(self) -> GroqClient:
        if self._groq is None:
            self._groq = get_groq_client()
        return self._groq

    def _tfidf_classifier(self) -> TFIDFClassifier:
        if self._tfidf is None:
            self._tfidf = get_tfidf_classifier()
        return self._tfidf

    def classify(self, question: str) -> ClassificationResult:
        """
        Classify a question into one of 6 technical topics.

        Decision flow:
          Step 1: Always run TF-IDF (it's instant)
          Step 2: If TF-IDF is confident enough → return TF-IDF result
          Step 3: If TF-IDF is uncertain AND Groq is available → use Groq
          Step 4: If Groq is down → return TF-IDF result anyway

        WHY run TF-IDF even when we'll use Groq?
          TF-IDF takes 1ms — essentially free.
          Its result is used as a fallback if Groq fails mid-request.
          We also log both predictions for model comparison / drift detection.
        """
        start = time.perf_counter()
        question = question.strip()

        # Step 1: Fast TF-IDF classification (always)
        tfidf_result = self._tfidf_classifier().predict(question)
        tfidf_topic = tfidf_result["topic"]
        tfidf_confidence = tfidf_result["confidence"]

        # Step 2: High-confidence TF-IDF → return immediately (no API call)
        if tfidf_confidence >= TFIDF_CONFIDENCE_THRESHOLD:
            return ClassificationResult(
                topic=tfidf_topic,
                confidence=tfidf_confidence,
                reasoning=f"TF-IDF classifier confident ({tfidf_confidence:.0%})",
                model_used="tfidf",
                latency_ms=round((time.perf_counter() - start) * 1000, 2),
            )

        # Step 3: Low confidence → try Groq for better accuracy
        groq = self._groq_client()
        if not groq.is_available():
            # Groq not configured — use TF-IDF regardless of confidence
            return ClassificationResult(
                topic=tfidf_topic,
                confidence=tfidf_confidence,
                reasoning="Groq not configured — using TF-IDF fallback",
                model_used="tfidf",
                latency_ms=round((time.perf_counter() - start) * 1000, 2),
            )

        try:
            groq_response = groq.complete(
                system_prompt=CLASSIFICATION_SYSTEM_PROMPT,
                user_message=f"Classify this interview question:\n\n{question}",
                temperature=0.1,
                max_tokens=150,
                json_mode=True,
            )

            # Validate Groq output
            groq_topic = groq_response.get("topic", "").strip()
            groq_confidence = float(groq_response.get("confidence", 0.5))
            reasoning = groq_response.get("reasoning", "LLM classification")

            if groq_topic not in TOPICS:
                # Groq returned an invalid topic — fall back to TF-IDF
                raise GroqClientError(f"Invalid topic '{groq_topic}' from Groq")

            return ClassificationResult(
                topic=groq_topic,
                confidence=groq_confidence,
                reasoning=reasoning,
                model_used="groq",
                latency_ms=round((time.perf_counter() - start) * 1000, 2),
            )

        except (GroqClientError, KeyError, ValueError) as e:
            # Circuit breaker: Groq failed → use TF-IDF
            return ClassificationResult(
                topic=tfidf_topic,
                confidence=tfidf_confidence,
                reasoning=f"Groq unavailable ({e}) — using TF-IDF fallback",
                model_used="tfidf_fallback",
                latency_ms=round((time.perf_counter() - start) * 1000, 2),
            )

    def classify_batch(self, questions: list[str]) -> list[ClassificationResult]:
        """Classify multiple questions. Each runs independently."""
        return [self.classify(q) for q in questions]


_classifier: SkillClassifier = None

def get_skill_classifier() -> SkillClassifier:
    global _classifier
    if _classifier is None:
        _classifier = SkillClassifier()
    return _classifier
