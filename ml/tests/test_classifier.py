"""
ml/tests/test_classifier.py — Classifier and Groq client tests

Test philosophy:
  - TF-IDF: test training, prediction accuracy, confidence
  - Groq client: test retry logic, error handling, JSON parsing
  - Orchestrator: test fallback routing, circuit breaker
  - Feedback: test fallback when Groq unavailable

Nothing requires a live Groq API or HuggingFace download.
"""

import pytest
from unittest.mock import MagicMock, patch, call
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from classifier.tfidf_classifier import TFIDFClassifier, TOPICS, TRAINING_DATA
from classifier.skill_classifier import SkillClassifier
from llm.groq_client import GroqClient, GroqClientError
from llm.feedback_generator import FeedbackGenerator


# ── TF-IDF Classifier tests ───────────────────────────────────────────────────

class TestTFIDFClassifier:

    @pytest.fixture
    def trained_classifier(self):
        clf = TFIDFClassifier()
        clf.train()
        return clf

    def test_train_returns_metrics(self):
        clf = TFIDFClassifier()
        metrics = clf.train()
        assert "train_accuracy" in metrics
        assert "n_samples" in metrics
        assert metrics["n_classes"] == 6

    def test_train_accuracy_above_threshold(self):
        """Model must learn training data — sanity check."""
        clf = TFIDFClassifier()
        metrics = clf.train()
        # Should overfit training data (we want to verify the pipeline works)
        assert metrics["train_accuracy"] > 0.8

    def test_predict_returns_valid_topic(self, trained_classifier):
        result = trained_classifier.predict("What is a mutex?")
        assert result["topic"] in TOPICS

    def test_predict_returns_confidence(self, trained_classifier):
        result = trained_classifier.predict("Explain TCP handshake")
        assert 0.0 <= result["confidence"] <= 1.0

    def test_predict_returns_all_scores(self, trained_classifier):
        result = trained_classifier.predict("What is a binary search tree?")
        assert "all_scores" in result
        assert len(result["all_scores"]) == 6
        assert set(result["all_scores"].keys()) == set(TOPICS)

    def test_all_scores_sum_to_one(self, trained_classifier):
        """Logistic regression outputs probabilities — must sum to 1.0."""
        result = trained_classifier.predict("Explain database indexing")
        total = sum(result["all_scores"].values())
        assert abs(total - 1.0) < 0.01

    def test_clear_dsa_question(self, trained_classifier):
        """Unambiguous question must classify correctly."""
        result = trained_classifier.predict(
            "What is the time complexity of binary search?"
        )
        assert result["topic"] == "DSA"

    def test_clear_cn_question(self, trained_classifier):
        result = trained_classifier.predict(
            "Explain the TCP three-way handshake protocol."
        )
        assert result["topic"] == "CN"

    def test_clear_dbms_question(self, trained_classifier):
        result = trained_classifier.predict(
            "What are the ACID properties of database transactions?"
        )
        assert result["topic"] == "DBMS"

    def test_clear_os_question(self, trained_classifier):
        result = trained_classifier.predict(
            "What is the difference between a process and a thread?"
        )
        assert result["topic"] == "OS"

    def test_clear_oop_question(self, trained_classifier):
        result = trained_classifier.predict(
            "Explain the four pillars of object-oriented programming."
        )
        assert result["topic"] == "OOP"

    def test_clear_system_design_question(self, trained_classifier):
        result = trained_classifier.predict(
            "How would you design a URL shortening service?"
        )
        assert result["topic"] == "System Design"

    def test_model_field_present(self, trained_classifier):
        result = trained_classifier.predict("test question")
        assert result["model"] == "tfidf_lr"

    def test_predict_without_training_auto_trains(self):
        """Calling predict() on untrained classifier must auto-train."""
        clf = TFIDFClassifier()
        result = clf.predict("What is quicksort?")
        assert result["topic"] in TOPICS
        assert clf._is_trained


# ── Groq client tests (all mocked) ───────────────────────────────────────────

class TestGroqClient:

    def test_is_available_with_key(self):
        client = GroqClient(api_key="gsk_test_key_12345")
        assert client.is_available() is True

    def test_is_not_available_without_key(self):
        client = GroqClient(api_key="")
        assert client.is_available() is False

    def test_is_not_available_with_placeholder(self):
        client = GroqClient(api_key="gsk_your_key_here")
        assert client.is_available() is False

    def test_complete_parses_json_response(self):
        """complete() must parse the LLM JSON string into a dict."""
        import json
        client = GroqClient(api_key="gsk_test")
        client._client = MagicMock()

        mock_response = MagicMock()
        mock_response.choices[0].message.content = json.dumps({
            "topic": "OS",
            "confidence": 0.95,
            "reasoning": "Question about mutex — synchronization"
        })
        mock_response.usage.total_tokens = 50
        client._client.chat.completions.create.return_value = mock_response

        result = client.complete("system prompt", "user message")
        assert result["topic"] == "OS"
        assert result["confidence"] == 0.95

    def test_complete_tracks_token_usage(self):
        import json
        client = GroqClient(api_key="gsk_test")
        client._client = MagicMock()

        mock_response = MagicMock()
        mock_response.choices[0].message.content = json.dumps({"topic": "DSA"})
        mock_response.usage.total_tokens = 75
        client._client.chat.completions.create.return_value = mock_response

        client.complete("sys", "user")
        assert client.total_tokens_used == 75

    def test_complete_retries_on_rate_limit(self):
        """Rate limit errors should trigger retries with backoff."""
        from groq import RateLimitError
        import json

        client = GroqClient(api_key="gsk_test")
        client._client = MagicMock()

        # First two calls raise RateLimitError, third succeeds
        good_response = MagicMock()
        good_response.choices[0].message.content = json.dumps({"result": "ok"})
        good_response.usage.total_tokens = 10

        client._client.chat.completions.create.side_effect = [
            RateLimitError.__new__(RateLimitError),
            RateLimitError.__new__(RateLimitError),
            good_response,
        ]

        # Patch sleep to avoid actual waiting in tests
        with patch('time.sleep'):
            result = client.complete("sys", "user", max_retries=3)

        assert result == {"result": "ok"}
        assert client._client.chat.completions.create.call_count == 3

    def test_complete_raises_after_max_retries(self):
        from groq import RateLimitError

        client = GroqClient(api_key="gsk_test")
        client._client = MagicMock()
        client._client.chat.completions.create.side_effect = RateLimitError.__new__(RateLimitError)

        with patch('time.sleep'):
            with pytest.raises(GroqClientError):
                client.complete("sys", "user", max_retries=2)

    def test_no_api_key_raises_value_error(self):
        client = GroqClient(api_key="")
        with pytest.raises(ValueError, match="GROQ_API_KEY"):
            client.complete("sys", "user")


# ── Orchestrator tests ────────────────────────────────────────────────────────

class TestSkillClassifier:

    def _make_classifier(self, groq_available=True, tfidf_confidence=0.9):
        mock_groq = MagicMock(spec=GroqClient)
        mock_groq.is_available.return_value = groq_available

        mock_tfidf = MagicMock(spec=TFIDFClassifier)
        mock_tfidf.predict.return_value = {
            "topic": "OS",
            "confidence": tfidf_confidence,
            "all_scores": {"OS": tfidf_confidence},
            "model": "tfidf_lr",
        }

        return SkillClassifier(groq_client=mock_groq, tfidf=mock_tfidf)

    def test_high_tfidf_confidence_skips_groq(self):
        """If TF-IDF is confident, Groq should not be called."""
        clf = self._make_classifier(tfidf_confidence=0.95)
        result = clf.classify("What is a mutex?")

        assert result.topic == "OS"
        assert result.model_used == "tfidf"
        clf._groq.complete.assert_not_called()

    def test_low_tfidf_confidence_calls_groq(self):
        """If TF-IDF is uncertain, call Groq for better accuracy."""
        clf = self._make_classifier(tfidf_confidence=0.45)
        clf._groq.complete.return_value = {
            "topic": "System Design",
            "confidence": 0.92,
            "reasoning": "Question about distributed systems",
        }

        result = clf.classify("How do you handle consistency in distributed caches?")
        assert result.topic == "System Design"
        assert result.model_used == "groq"

    def test_groq_unavailable_uses_tfidf_regardless(self):
        """Circuit breaker: Groq not configured → always use TF-IDF."""
        clf = self._make_classifier(groq_available=False, tfidf_confidence=0.45)
        result = clf.classify("Some ambiguous question")

        assert result.model_used == "tfidf"
        clf._groq.complete.assert_not_called()

    def test_groq_failure_falls_back_to_tfidf(self):
        """Circuit breaker: Groq fails mid-request → use TF-IDF."""
        clf = self._make_classifier(tfidf_confidence=0.45)
        clf._groq.complete.side_effect = GroqClientError("connection timeout")

        result = clf.classify("Ambiguous technical question")
        assert result.model_used == "tfidf_fallback"
        assert result.topic == "OS"  # TF-IDF result

    def test_groq_invalid_topic_falls_back(self):
        """If Groq returns a topic not in our list, fall back to TF-IDF."""
        clf = self._make_classifier(tfidf_confidence=0.45)
        clf._groq.complete.return_value = {
            "topic": "Mathematics",   # Not in our TOPICS list
            "confidence": 0.9,
            "reasoning": "...",
        }

        result = clf.classify("Some question")
        assert result.model_used == "tfidf_fallback"

    def test_result_has_latency(self):
        clf = self._make_classifier(tfidf_confidence=0.95)
        result = clf.classify("What is a binary tree?")
        assert result.latency_ms >= 0.0


# ── Feedback generator tests ──────────────────────────────────────────────────

class TestFeedbackGenerator:

    def test_fallback_returns_when_groq_unavailable(self):
        mock_groq = MagicMock(spec=GroqClient)
        mock_groq.is_available.return_value = False

        gen = FeedbackGenerator(groq_client=mock_groq)
        result = gen.generate(
            question="What is a BST?",
            ideal_answer="Binary search tree with left < root < right",
            candidate_answer="A tree data structure",
            similarity_score=0.4,
            confidence_score=0.3,
            keywords_matched=[],
            topic="DSA",
            grade="Needs Work",
        )

        assert "assessment" in result
        assert "improvements" in result
        assert result["generated_by"] == "fallback"

    def test_groq_feedback_returned_when_available(self):
        import json
        mock_groq = MagicMock(spec=GroqClient)
        mock_groq.is_available.return_value = True
        mock_groq.complete.return_value = {
            "assessment": "Good answer covering the key BST properties.",
            "strengths": "Correctly mentioned the ordering invariant.",
            "improvements": "Also discuss time complexity for operations.",
            "hint": "What is the worst-case time complexity of search in a BST?",
        }

        gen = FeedbackGenerator(groq_client=mock_groq)
        result = gen.generate(
            question="What is a BST?",
            ideal_answer="Binary search tree...",
            candidate_answer="A tree where left < root < right with O(log n) search",
            similarity_score=0.82,
            confidence_score=0.75,
            keywords_matched=["binary search", "O(log n)"],
            topic="DSA",
            grade="Good",
        )

        assert result["assessment"] == "Good answer covering the key BST properties."
        assert result["generated_by"] == "groq"

    def test_groq_error_falls_back_gracefully(self):
        mock_groq = MagicMock(spec=GroqClient)
        mock_groq.is_available.return_value = True
        mock_groq.complete.side_effect = GroqClientError("timeout")

        gen = FeedbackGenerator(groq_client=mock_groq)
        result = gen.generate(
            question="Q", ideal_answer="A", candidate_answer="B",
            similarity_score=0.5, confidence_score=0.5,
            keywords_matched=[], topic="DSA", grade="Fair",
        )

        assert result["generated_by"] == "fallback"
        assert "assessment" in result
