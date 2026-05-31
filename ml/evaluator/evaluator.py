"""
ml/evaluator/evaluator.py — Answer Evaluation Engine

This module does the intellectual heavy lifting:
  1. Embed the candidate's answer and the ideal answer
  2. Compute cosine similarity (content match)
  3. Compute confidence score (communication quality)
  4. Combine into a final score with feedback

WHY is this a class with a lazy-loaded model?
  Loading a Sentence Transformer takes ~2-3 seconds and uses ~500MB RAM.
  If we loaded it at import time, the app would be slow to start and
  every test that imports this module would load the model.

  Lazy loading: the model loads on the FIRST call to evaluate().
  Subsequent calls reuse the already-loaded model from memory.
  This is the "singleton with lazy init" pattern.

  In production: load eagerly at startup via FastAPI lifespan so the
  FIRST real user request doesn't pay the loading cost.
"""

import re
import time
from dataclasses import dataclass
from typing import Optional

import numpy as np


@dataclass
class EvaluationResult:
    """
    The complete output of one answer evaluation.

    WHY a dataclass and not a plain dict?
      Type safety. A dict["similarity_scroe"] silently returns KeyError.
      A dataclass.similarity_scroe raises AttributeError AND is caught by
      type checkers (mypy, pyright) before runtime.

    WHY dataclass and not Pydantic BaseModel?
      Pydantic is for HTTP boundaries (serialization, validation).
      Dataclasses are for internal data structures — no overhead.
      The ML service converts this to a dict when sending HTTP responses.
    """
    similarity_score: float      # 0.0–1.0 — semantic content match
    confidence_score: float      # 0.0–1.0 — communication quality
    final_score: float           # 0.0–100.0 — the displayed grade
    grade: str                   # "Excellent" | "Good" | "Fair" | "Needs Work"
    feedback: str                # Human-readable explanation
    inference_time_ms: float     # Observability — how long did scoring take?
    keywords_matched: list[str]  # Which key concepts were mentioned


# Weights for the final score
# WHY 70/30 and not 50/50?
#   In a technical interview, WHAT you say matters more than HOW you say it.
#   A concise, accurate answer should score higher than a verbose but correct one.
#   70% content, 30% communication quality reflects this.
SIMILARITY_WEIGHT = 0.70
CONFIDENCE_WEIGHT = 0.30

# Topic-specific technical keywords — used for keyword coverage scoring
# WHY hardcode keywords here and not use NLP to extract them?
#   For a controlled interview domain, curated keywords are more reliable
#   than unsupervised extraction. An interviewer knows what concepts matter.
#   This is a conscious tradeoff: precision over generality.
TOPIC_KEYWORDS = {
    "DSA": [
        "time complexity", "space complexity", "big o", "O(n)", "O(log n)",
        "array", "linked list", "stack", "queue", "tree", "graph", "hash",
        "sort", "search", "recursion", "dynamic programming", "greedy",
        "binary search", "traversal", "pointer", "node", "edge",
    ],
    "OS": [
        "process", "thread", "deadlock", "mutex", "semaphore", "scheduling",
        "memory", "virtual memory", "paging", "segmentation", "cache",
        "interrupt", "system call", "kernel", "user space", "context switch",
        "race condition", "concurrency", "synchronization", "ipc",
    ],
    "DBMS": [
        "acid", "transaction", "index", "normalization", "join", "foreign key",
        "primary key", "sql", "nosql", "query", "schema", "relation",
        "isolation", "consistency", "durability", "atomicity", "b-tree",
        "lock", "mvcc", "replication", "sharding",
    ],
    "CN": [
        "tcp", "udp", "http", "https", "dns", "ip", "osi", "layer",
        "socket", "protocol", "packet", "router", "switch", "bandwidth",
        "latency", "three-way handshake", "ssl", "tls", "firewall",
        "load balancer", "cdn", "rest", "grpc",
    ],
    "OOP": [
        "class", "object", "inheritance", "polymorphism", "encapsulation",
        "abstraction", "interface", "override", "overload", "constructor",
        "method", "attribute", "design pattern", "solid", "coupling",
        "cohesion", "dependency injection", "composition",
    ],
    "System Design": [
        "scalability", "availability", "consistency", "partition", "cap theorem",
        "load balancing", "caching", "database", "microservices", "api gateway",
        "message queue", "kafka", "redis", "cdn", "horizontal scaling",
        "vertical scaling", "sharding", "replication", "fault tolerance",
        "rate limiting", "service discovery",
    ],
}


class AnswerEvaluator:
    """
    Evaluates candidate interview answers using semantic similarity.

    Lifecycle:
      1. Instantiate once at startup (or lazily on first call)
      2. Call .evaluate() for each answer — reuses the loaded model
      3. Returns an EvaluationResult dataclass

    Thread safety:
      SentenceTransformer.encode() is NOT thread-safe by default.
      In production with multiple workers, each worker process loads
      its own model instance (Uvicorn's --workers flag creates separate processes).
      Threads within one process share the model — use a threading.Lock if needed.
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model_name = model_name
        self._model = None   # Lazy load
        self._load_time_ms: Optional[float] = None

    def _load_model(self):
        """
        Load the Sentence Transformer model into memory.

        Called once on first use. Subsequent calls are instant (model is cached).

        WHY store timing?
          Model load time is an important operational metric.
          If load time degrades, it signals:
            - Cold container start (acceptable)
            - Slow disk I/O (needs investigation)
            - Model file corruption (needs alert)
        """
        if self._model is not None:
            return

        start = time.perf_counter()
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.model_name)
            self._load_time_ms = (time.perf_counter() - start) * 1000
        except Exception as e:
            # Raise a clear error — "model not loaded" is hard to debug
            raise RuntimeError(
                f"Failed to load Sentence Transformer '{self.model_name}'. "
                f"Ensure the model is available (pre-downloaded in Docker image). "
                f"Original error: {e}"
            )

    def _embed(self, texts: list[str]) -> np.ndarray:
        """
        Convert a list of strings into embedding vectors.

        Returns shape: (len(texts), 384) — one 384-dim vector per text.

        WHY batch encoding?
          Encoding one sentence at a time is inefficient — the transformer
          model can process multiple sentences in parallel on the same forward pass.
          Batching 2 sentences vs 2 separate calls: ~same time, not 2x time.
          At scale (100 sentences): batch is 10-20x faster than sequential.
        """
        self._load_model()
        return self._model.encode(
            texts,
            normalize_embeddings=True,  # L2-normalize → dot product = cosine similarity
            show_progress_bar=False,
            batch_size=32,
        )

    def _cosine_similarity(self, vec_a: np.ndarray, vec_b: np.ndarray) -> float:
        """
        Compute cosine similarity between two normalized vectors.

        WHY just a dot product?
          When vectors are L2-normalized (unit vectors), their dot product IS
          the cosine similarity. No division needed — the norms are both 1.0.

          cos(θ) = (A · B) / (‖A‖ × ‖B‖) = (A · B) / (1 × 1) = A · B

          This is why we pass normalize_embeddings=True to encode() above.
          It's a minor optimization but reveals understanding of the math.

        Returns: float in [0, 1] (always positive for L2-normalized BERT embeddings)
        """
        return float(np.dot(vec_a, vec_b))

    def _confidence_score(self, answer: str, topic: str) -> tuple[float, list[str]]:
        """
        Score the communication quality of an answer.

        Confidence ≠ correctness. It measures:
          1. Length adequacy: too short = incomplete, too long = padding
          2. Keyword coverage: did they mention key concepts?
          3. Structural clarity: sentences, not word salad

        WHY not use the model for this?
          The semantic similarity already captures content.
          Confidence is a proxy for "would this answer satisfy an interviewer?"
          — which depends on surface features (length, keywords) more than semantics.
          Rule-based scoring is more interpretable and debuggable here.

        Returns: (confidence_score 0.0-1.0, list of matched keywords)
        """
        answer_lower = answer.lower()
        words = answer_lower.split()
        word_count = len(words)

        # ── Component 1: Length score ────────────────────────────────────────
        # Empirically: good interview answers are 50-300 words
        # < 20 words: too brief to demonstrate understanding
        # > 500 words: rambling, reduces confidence
        if word_count < 20:
            length_score = word_count / 20       # Linear ramp up
        elif word_count <= 300:
            length_score = 1.0                   # Sweet spot
        elif word_count <= 500:
            length_score = 1.0 - (word_count - 300) / 400   # Gentle penalty
        else:
            length_score = 0.5                   # Floor — very long answers

        # ── Component 2: Keyword coverage ───────────────────────────────────
        keywords = TOPIC_KEYWORDS.get(topic, [])
        matched = [kw for kw in keywords if kw.lower() in answer_lower]

        if not keywords:
            keyword_score = 0.5   # No keywords for this topic — neutral
        else:
            # Diminishing returns: 0→1 keyword = big gain, 5→6 = small gain
            # sqrt gives a concave curve that rewards breadth without requiring exhaustive coverage
            coverage = len(matched) / len(keywords)
            keyword_score = min(1.0, coverage * 3)  # 33% coverage → score of 1.0

        # ── Component 3: Structural score ────────────────────────────────────
        # Count sentences as a proxy for structured thinking
        sentence_count = len(re.split(r'[.!?]+', answer.strip()))
        if sentence_count >= 3:
            structure_score = 1.0
        elif sentence_count == 2:
            structure_score = 0.7
        else:
            structure_score = 0.4   # Single-sentence answers are rarely sufficient

        # Weighted combination
        confidence = (
            0.35 * length_score +
            0.45 * keyword_score +
            0.20 * structure_score
        )
        return min(1.0, confidence), matched

    def _generate_feedback(
        self,
        similarity: float,
        confidence: float,
        final: float,
        matched_keywords: list[str],
        topic: str,
    ) -> tuple[str, str]:
        """
        Generate human-readable feedback and a letter grade.

        WHY rule-based feedback and not LLM-generated?
          Rule-based feedback is:
            - Deterministic: same score → same feedback (no hallucinations)
            - Fast: no extra model call
            - Debuggable: easy to trace which rule fired
          LLM-generated feedback is better quality but adds 500ms+ and cost.
          For MVP: rules. For v2: LLM with the rule scores as context.

        In production at companies like Khanmigo (Khan Academy's AI tutor),
        they use a hybrid: rule-based scoring + LLM for the feedback text.
        """
        # Determine grade thresholds
        if final >= 85:
            grade = "Excellent"
        elif final >= 70:
            grade = "Good"
        elif final >= 50:
            grade = "Fair"
        else:
            grade = "Needs Work"

        # Build contextual feedback
        parts = []

        # Content feedback
        if similarity >= 0.85:
            parts.append("Your answer captures the key concepts accurately.")
        elif similarity >= 0.65:
            parts.append("Your answer covers the main ideas but misses some nuances.")
        elif similarity >= 0.45:
            parts.append("Your answer touches on the topic but lacks depth.")
        else:
            parts.append("Your answer doesn't closely match the expected concepts.")

        # Keyword feedback
        topic_kws = TOPIC_KEYWORDS.get(topic, [])
        missed = [kw for kw in topic_kws[:8] if kw not in matched_keywords]
        if matched_keywords:
            parts.append(f"Good use of: {', '.join(matched_keywords[:4])}.")
        if missed and len(missed) <= 5:
            parts.append(f"Consider mentioning: {', '.join(missed[:3])}.")

        # Confidence feedback
        if confidence < 0.4:
            parts.append("Try to elaborate more — a good interview answer is typically 3-5 sentences.")
        elif confidence > 0.8:
            parts.append("Well-structured response.")

        feedback = " ".join(parts)
        return grade, feedback

    def evaluate(
        self,
        candidate_answer: str,
        ideal_answer: str,
        topic: str = "General",
    ) -> EvaluationResult:
        """
        Main public API — evaluate one candidate answer.

        Args:
            candidate_answer: What the candidate said
            ideal_answer: The reference answer from our question bank
            topic: Which skill domain (DSA, OS, DBMS, CN, OOP, System Design)

        Returns:
            EvaluationResult with all scores and feedback

        Performance budget (CPU, no GPU):
          Model encoding: ~40-80ms for 2 sentences
          Cosine similarity: ~0.01ms (pure numpy, trivially fast)
          Confidence scoring: ~1ms (regex + string ops)
          Total: ~50-100ms per evaluation
        """
        start = time.perf_counter()

        # Input validation
        candidate_answer = candidate_answer.strip()
        ideal_answer = ideal_answer.strip()

        if not candidate_answer:
            return EvaluationResult(
                similarity_score=0.0,
                confidence_score=0.0,
                final_score=0.0,
                grade="Needs Work",
                feedback="No answer provided.",
                inference_time_ms=0.0,
                keywords_matched=[],
            )

        # ── Encode both texts in one batch call ──────────────────────────────
        embeddings = self._embed([candidate_answer, ideal_answer])
        candidate_vec = embeddings[0]
        ideal_vec = embeddings[1]

        # ── Semantic similarity ───────────────────────────────────────────────
        similarity = self._cosine_similarity(candidate_vec, ideal_vec)
        # Clip to [0, 1] — normalized BERT embeddings should always be positive,
        # but floating point arithmetic can produce values like -0.001
        similarity = float(np.clip(similarity, 0.0, 1.0))

        # ── Confidence scoring ────────────────────────────────────────────────
        confidence, matched_keywords = self._confidence_score(candidate_answer, topic)

        # ── Weighted final score ──────────────────────────────────────────────
        final_raw = SIMILARITY_WEIGHT * similarity + CONFIDENCE_WEIGHT * confidence
        final_score = round(final_raw * 100, 1)   # Convert to 0-100 scale

        # ── Generate feedback ─────────────────────────────────────────────────
        grade, feedback = self._generate_feedback(
            similarity, confidence, final_score, matched_keywords, topic
        )

        inference_time_ms = (time.perf_counter() - start) * 1000

        return EvaluationResult(
            similarity_score=round(similarity, 4),
            confidence_score=round(confidence, 4),
            final_score=final_score,
            grade=grade,
            feedback=feedback,
            inference_time_ms=round(inference_time_ms, 2),
            keywords_matched=matched_keywords,
        )

    def evaluate_batch(
        self,
        pairs: list[tuple[str, str]],
        topics: list[str] | None = None,
    ) -> list[EvaluationResult]:
        """
        Evaluate multiple answer-ideal pairs in one model call.

        WHY batch evaluation?
          If a session has 5 questions, evaluating them one by one means
          5 model forward passes. Batching all 10 texts (5 answers + 5 ideals)
          into one encode() call is ~2-3x faster due to GPU/CPU parallelism.

          On CPU with batch_size=32: each forward pass costs roughly the same
          whether it processes 1 sentence or 32 sentences. Fill the batch.

        Args:
            pairs: list of (candidate_answer, ideal_answer) tuples
            topics: corresponding list of topic names (optional)
        """
        if not pairs:
            return []

        topics = topics or ["General"] * len(pairs)
        all_texts = []
        for candidate, ideal in pairs:
            all_texts.append(candidate.strip())
            all_texts.append(ideal.strip())

        # One encode() call for all texts
        embeddings = self._embed(all_texts)

        results = []
        for i, ((candidate, ideal), topic) in enumerate(zip(pairs, topics)):
            candidate_vec = embeddings[i * 2]
            ideal_vec = embeddings[i * 2 + 1]

            similarity = float(np.clip(np.dot(candidate_vec, ideal_vec), 0.0, 1.0))
            confidence, matched = self._confidence_score(candidate, topic)
            final_score = round((SIMILARITY_WEIGHT * similarity + CONFIDENCE_WEIGHT * confidence) * 100, 1)
            grade, feedback = self._generate_feedback(similarity, confidence, final_score, matched, topic)

            results.append(EvaluationResult(
                similarity_score=round(similarity, 4),
                confidence_score=round(confidence, 4),
                final_score=final_score,
                grade=grade,
                feedback=feedback,
                inference_time_ms=0.0,  # Not tracked per-item in batch
                keywords_matched=matched,
            ))

        return results


# ── Module-level singleton ─────────────────────────────────────────────────────
# WHY module-level? One evaluator per process — shared across all requests.
# The model weights (~90MB) are loaded once and reused.
_evaluator: Optional[AnswerEvaluator] = None


def get_evaluator() -> AnswerEvaluator:
    global _evaluator
    if _evaluator is None:
        _evaluator = AnswerEvaluator()
    return _evaluator
