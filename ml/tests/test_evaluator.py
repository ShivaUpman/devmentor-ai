"""
ml/tests/test_evaluator.py — Evaluator unit tests

Critical design decision: we test EVERYTHING except the neural network itself.
  - The embedding step requires a live model (network call in dev environment)
  - Everything else — cosine math, confidence scoring, feedback generation,
    grade assignment, batch logic — is pure Python and fully testable
"""

import numpy as np
import pytest
from unittest.mock import MagicMock

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from evaluator.evaluator import (
    AnswerEvaluator,
    EvaluationResult,
    SIMILARITY_WEIGHT,
    CONFIDENCE_WEIGHT,
    TOPIC_KEYWORDS,
)


def make_evaluator_with_mock_model() -> AnswerEvaluator:
    evaluator = AnswerEvaluator(model_name="mock-model")
    evaluator._model = MagicMock()
    return evaluator


def make_similar_embeddings(similarity: float = 0.9) -> np.ndarray:
    a = np.array([1.0, 0.0, 0.0, 0.0, 0.0])
    theta = np.arccos(np.clip(similarity, -1, 1))
    b = np.array([np.cos(theta), np.sin(theta), 0.0, 0.0, 0.0])
    return np.stack([a, b])


class TestCosineSimilarity:
    def test_identical_vectors_give_one(self):
        e = make_evaluator_with_mock_model()
        v = np.array([0.5, 0.5, 0.5, 0.5])
        v = v / np.linalg.norm(v)
        assert abs(e._cosine_similarity(v, v) - 1.0) < 1e-6

    def test_orthogonal_vectors_give_zero(self):
        e = make_evaluator_with_mock_model()
        a = np.array([1.0, 0.0])
        b = np.array([0.0, 1.0])
        assert abs(e._cosine_similarity(a, b)) < 1e-6

    def test_sixty_degree_angle(self):
        e = make_evaluator_with_mock_model()
        a = np.array([1.0, 0.0])
        b = np.array([0.5, np.sqrt(3)/2])
        assert abs(e._cosine_similarity(a, b) - 0.5) < 1e-6


class TestConfidenceScoring:
    def test_short_answer_scores_low(self):
        e = make_evaluator_with_mock_model()
        score, _ = e._confidence_score("Yes.", "DSA")
        assert score < 0.4

    def test_rich_answer_scores_higher(self):
        e = make_evaluator_with_mock_model()
        answer = (
            "A binary search tree stores values where left child is less than root and "
            "right child is greater. Search has O(log n) time complexity on balanced trees. "
            "Common traversals include in-order, pre-order, and post-order. "
            "Space complexity is O(h) where h is tree height. Insertion and deletion "
            "maintain the BST property through rotations in self-balancing variants."
        )
        score, keywords = e._confidence_score(answer, "DSA")
        assert score > 0.5
        assert len(keywords) > 0

    def test_keyword_match_case_insensitive(self):
        e = make_evaluator_with_mock_model()
        _, kws = e._confidence_score("TIME COMPLEXITY and SPACE COMPLEXITY matter.", "DSA")
        matched_lower = [k.lower() for k in kws]
        assert "time complexity" in matched_lower

    def test_returned_keywords_are_valid(self):
        e = make_evaluator_with_mock_model()
        _, matched = e._confidence_score("tcp udp http dns protocol packet router", "CN")
        valid = [k.lower() for k in TOPIC_KEYWORDS["CN"]]
        for kw in matched:
            assert kw.lower() in valid


class TestGradeAssignment:
    def _grade(self, score):
        e = make_evaluator_with_mock_model()
        grade, _ = e._generate_feedback(0.8, 0.7, score, [], "DSA")
        return grade

    def test_90_is_excellent(self): assert self._grade(90) == "Excellent"
    def test_75_is_good(self): assert self._grade(75) == "Good"
    def test_55_is_fair(self): assert self._grade(55) == "Fair"
    def test_30_is_needs_work(self): assert self._grade(30) == "Needs Work"
    def test_boundary_85_is_excellent(self): assert self._grade(85) == "Excellent"
    def test_boundary_70_is_good(self): assert self._grade(70) == "Good"


class TestEvaluatePipeline:
    def _run(self, similarity, answer=None, topic="DSA"):
        e = make_evaluator_with_mock_model()
        emb = make_similar_embeddings(similarity)
        e._model.encode.return_value = emb
        ans = answer or ("Binary search uses O(log n) time complexity on sorted arrays. " * 4)
        return e.evaluate(candidate_answer=ans, ideal_answer="Reference ideal answer text.", topic=topic)

    def test_high_similarity_scores_high(self):
        assert self._run(0.95).final_score >= 70

    def test_low_similarity_scores_low(self):
        assert self._run(0.10).final_score < 50

    def test_empty_answer_returns_zero(self):
        e = make_evaluator_with_mock_model()
        r = e.evaluate("   ", "ideal", "DSA")
        assert r.final_score == 0.0
        assert r.grade == "Needs Work"

    def test_scores_in_valid_range(self):
        r = self._run(0.75)
        assert 0.0 <= r.similarity_score <= 1.0
        assert 0.0 <= r.confidence_score <= 1.0
        assert 0.0 <= r.final_score <= 100.0

    def test_result_fields_all_present(self):
        r = self._run(0.7)
        for field in ['similarity_score','confidence_score','final_score','grade','feedback','keywords_matched']:
            assert hasattr(r, field), f"Missing field: {field}"

    def test_weights_applied(self):
        """Verify the 70/30 weight contract is honored."""
        r = self._run(0.8)
        sim_contribution = SIMILARITY_WEIGHT * r.similarity_score * 100
        assert r.final_score >= sim_contribution * 0.85

    def test_dsa_keywords_detected(self):
        answer = (
            "Binary search runs in O(log n) time complexity. "
            "It requires a sorted array as input. "
            "Space complexity is O(1) for the iterative version."
        )
        r = self._run(0.8, answer=answer, topic="DSA")
        assert len(r.keywords_matched) > 0

    def test_batch_returns_correct_count(self):
        e = make_evaluator_with_mock_model()
        n = 3
        e._model.encode.return_value = np.tile(
            make_similar_embeddings(0.8)[0], (n * 2, 1)
        )
        results = e.evaluate_batch([("a", "b")] * n, topics=["DSA"] * n)
        assert len(results) == n

    def test_batch_calls_encode_once(self):
        """Single encode() call is the whole point of batching."""
        e = make_evaluator_with_mock_model()
        n = 4
        e._model.encode.return_value = np.tile(
            make_similar_embeddings(0.8)[0], (n * 2, 1)
        )
        e.evaluate_batch([("ans", "ideal")] * n, topics=["OS"] * n)
        assert e._model.encode.call_count == 1
