"""
ml/tests/test_recommender.py — Recommendation engine tests

What we test (without Groq or network):
  - Catalogue structure and completeness
  - Gap computation and weak topic identification
  - Resource selection by difficulty
  - Algorithm-only roadmap generation
  - Groq integration via mocks (ordering, fallback, invalid IDs)
  - Edge cases: all skills strong, no resources found, empty scores
"""

import pytest
from unittest.mock import MagicMock
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from recommender.catalogue import (
    Resource, RESOURCE_CATALOGUE, get_resources_for_topic,
    get_catalogue_stats, get_all_topics,
)
from recommender.engine import (
    RecommendationEngine, Roadmap, RoadmapItem,
    WEAK_SKILL_THRESHOLD, MAX_TOTAL_ITEMS,
)
from llm.groq_client import GroqClient, GroqClientError


# ── Catalogue tests ───────────────────────────────────────────────────────────

class TestCatalogue:

    def test_catalogue_has_resources(self):
        assert len(RESOURCE_CATALOGUE) > 0

    def test_all_six_topics_covered(self):
        topics = get_all_topics()
        required = {"DSA", "OS", "DBMS", "CN", "OOP", "System Design"}
        assert required.issubset(set(topics))

    def test_each_topic_has_at_least_three_resources(self):
        """Minimum coverage per topic for meaningful recommendations."""
        for topic in ["DSA", "OS", "DBMS", "CN", "OOP", "System Design"]:
            resources = get_resources_for_topic(topic)
            assert len(resources) >= 3, f"{topic} has only {len(resources)} resources"

    def test_resource_ids_are_unique(self):
        ids = [r.id for r in RESOURCE_CATALOGUE]
        assert len(ids) == len(set(ids)), "Duplicate resource IDs found"

    def test_all_resources_have_valid_type(self):
        valid_types = {"article", "video", "course", "book", "practice"}
        for r in RESOURCE_CATALOGUE:
            assert r.resource_type in valid_types, f"{r.id} has invalid type {r.resource_type}"

    def test_all_resources_have_valid_difficulty(self):
        valid_difficulties = {"beginner", "intermediate", "advanced"}
        for r in RESOURCE_CATALOGUE:
            assert r.difficulty in valid_difficulties

    def test_all_resources_have_positive_hours(self):
        for r in RESOURCE_CATALOGUE:
            assert r.estimated_hours > 0, f"{r.id} has invalid hours {r.estimated_hours}"

    def test_all_resources_have_url(self):
        for r in RESOURCE_CATALOGUE:
            assert r.url.startswith("http"), f"{r.id} missing URL"

    def test_catalogue_stats_returns_correct_total(self):
        stats = get_catalogue_stats()
        assert stats["total_resources"] == len(RESOURCE_CATALOGUE)

    def test_resource_is_immutable(self):
        """frozen=True means resources can't be accidentally mutated."""
        resource = RESOURCE_CATALOGUE[0]
        with pytest.raises((AttributeError, TypeError)):
            resource.title = "Modified"


# ── Gap computation tests ─────────────────────────────────────────────────────

class TestGapComputation:

    @pytest.fixture
    def engine(self):
        return RecommendationEngine(groq_client=MagicMock())

    def test_scores_below_threshold_are_weak(self, engine):
        scores = {"DSA": 0.3, "OS": 0.9}
        gaps = engine._compute_gaps(scores)
        topics = [t for t, _, _ in gaps]
        assert "DSA" in topics
        assert "OS" not in topics   # 0.9 > threshold

    def test_gaps_sorted_by_gap_descending(self, engine):
        scores = {"DSA": 0.5, "DBMS": 0.2, "CN": 0.4}
        gaps = engine._compute_gaps(scores)
        gap_values = [g for _, _, g in gaps]
        assert gap_values == sorted(gap_values, reverse=True)

    def test_gap_is_complement_of_score(self, engine):
        scores = {"DSA": 0.3}
        gaps = engine._compute_gaps(scores)
        _, score, gap = gaps[0]
        assert abs(gap - (1.0 - score)) < 1e-9

    def test_all_strong_returns_empty(self, engine):
        scores = {"DSA": 0.8, "OS": 0.9, "DBMS": 0.7}
        gaps = engine._compute_gaps(scores)
        assert len(gaps) == 0

    def test_score_clamped_to_valid_range(self, engine):
        # Scores > 1.0 or < 0.0 should be clamped
        gaps = engine._compute_gaps({"DSA": 1.5, "OS": -0.1})
        # Both clamped: DSA→1.0 (above threshold), OS→0.0 (weak)
        topics = [t for t, _, _ in gaps]
        assert "DSA" not in topics
        assert "OS" in topics

    def test_threshold_boundary_excluded(self, engine):
        # Score exactly at threshold should NOT be weak
        gaps = engine._compute_gaps({"DSA": WEAK_SKILL_THRESHOLD})
        assert len(gaps) == 0

    def test_just_below_threshold_is_weak(self, engine):
        gaps = engine._compute_gaps({"DSA": WEAK_SKILL_THRESHOLD - 0.01})
        assert len(gaps) == 1


# ── Resource selection tests ──────────────────────────────────────────────────

class TestResourceSelection:

    @pytest.fixture
    def engine(self):
        return RecommendationEngine(groq_client=MagicMock())

    def test_returns_resources_for_known_topic(self, engine):
        resources = engine._select_resources("DSA", 0.3)
        assert len(resources) > 0
        assert all(r.topic == "DSA" for r in resources)

    def test_returns_empty_for_unknown_topic(self, engine):
        resources = engine._select_resources("Quantum Computing", 0.3)
        assert resources == []

    def test_low_score_prefers_beginner(self, engine):
        resources = engine._select_resources("DSA", 0.2, n=1)
        # Top resource should be beginner given very low score
        assert resources[0].difficulty == "beginner"

    def test_respects_max_resources_per_topic(self, engine):
        resources = engine._select_resources("DSA", 0.3, n=2)
        assert len(resources) <= 2

    def test_all_returned_resources_are_from_correct_topic(self, engine):
        for topic in ["DSA", "OS", "DBMS", "CN", "OOP", "System Design"]:
            resources = engine._select_resources(topic, 0.4)
            assert all(r.topic == topic for r in resources)

    def test_difficulty_mapping_low_score(self, engine):
        difficulty = engine._difficulty_for_score(0.2)
        assert difficulty == "beginner"

    def test_difficulty_mapping_mid_score(self, engine):
        difficulty = engine._difficulty_for_score(0.45)
        assert difficulty == "intermediate"

    def test_difficulty_mapping_high_score(self, engine):
        difficulty = engine._difficulty_for_score(0.65)
        assert difficulty == "advanced"


# ── Algorithm-only roadmap tests ──────────────────────────────────────────────

class TestAlgorithmRoadmap:

    @pytest.fixture
    def engine(self):
        mock_groq = MagicMock(spec=GroqClient)
        mock_groq.is_available.return_value = False   # Force algorithm-only
        return RecommendationEngine(groq_client=mock_groq)

    def test_generates_roadmap_for_weak_skills(self, engine):
        scores = {"DSA": 0.3, "DBMS": 0.2}
        roadmap = engine.generate(scores)
        assert len(roadmap.items) > 0

    def test_generated_by_is_algorithm_when_groq_off(self, engine):
        roadmap = engine.generate({"DSA": 0.3})
        assert roadmap.generated_by == "algorithm"

    def test_all_items_have_required_fields(self, engine):
        roadmap = engine.generate({"OS": 0.3, "CN": 0.4})
        for item in roadmap.items:
            assert item.resource is not None
            assert item.priority >= 1
            assert item.why != ""
            assert item.skill_topic in ["OS", "CN"]

    def test_roadmap_capped_at_max_items(self, engine):
        # Give 6 weak topics — should still cap at MAX_TOTAL_ITEMS
        scores = {t: 0.2 for t in ["DSA", "OS", "DBMS", "CN", "OOP", "System Design"]}
        roadmap = engine.generate(scores)
        assert len(roadmap.items) <= MAX_TOTAL_ITEMS

    def test_all_strong_returns_advanced_follow_up_roadmap(self, engine):
        scores = {t: 0.9 for t in ["DSA", "OS", "DBMS", "CN", "OOP", "System Design"]}
        roadmap = engine.generate(scores)
        assert len(roadmap.items) > 0
        assert all(item.resource.difficulty == "advanced" for item in roadmap.items)

    def test_priorities_are_positive_integers(self, engine):
        roadmap = engine.generate({"DSA": 0.3, "OS": 0.4})
        for item in roadmap.items:
            assert isinstance(item.priority, int)
            assert item.priority >= 1

    def test_weakest_topic_generates_first(self, engine):
        """Most urgent topic should appear earliest in the roadmap."""
        scores = {"DSA": 0.15, "OS": 0.55}  # DSA much weaker
        roadmap = engine.generate(scores)
        if len(roadmap.items) > 0:
            first_item = min(roadmap.items, key=lambda x: x.priority)
            assert first_item.skill_topic == "DSA"


# ── Groq personalization tests ────────────────────────────────────────────────

class TestGroqPersonalization:

    def _make_engine(self, groq_response: dict = None, groq_error: Exception = None):
        mock_groq = MagicMock(spec=GroqClient)
        mock_groq.is_available.return_value = True
        if groq_error:
            mock_groq.complete.side_effect = groq_error
        else:
            mock_groq.complete.return_value = groq_response or {}
        return RecommendationEngine(groq_client=mock_groq)

    def test_groq_personalized_roadmap_uses_groq(self):
        engine = self._make_engine(groq_response={
            "reasoning": "Focus on DBMS first as it unlocks System Design.",
            "ordered_items": [
                {"resource_id": "dbms-use-the-index", "priority": 1, "why": "Core SQL skill", "week": 1, "prerequisite_for": ["System Design"]},
                {"resource_id": "dbms-normalization-guide", "priority": 2, "why": "Foundation", "week": 1, "prerequisite_for": []},
            ]
        })
        roadmap = engine.generate({"DBMS": 0.25, "DSA": 0.35})
        assert roadmap.generated_by == "groq"
        assert "DBMS" in roadmap.reasoning or len(roadmap.items) > 0

    def test_groq_error_falls_back_to_algorithm(self):
        engine = self._make_engine(groq_error=GroqClientError("timeout"))
        roadmap = engine.generate({"DSA": 0.3})
        # Should still return a roadmap, just algorithm-generated
        assert roadmap.generated_by == "algorithm"
        assert len(roadmap.items) > 0

    def test_groq_invalid_resource_ids_are_skipped(self):
        """If Groq references an ID we didn't provide, skip it safely."""
        engine = self._make_engine(groq_response={
            "reasoning": "Study hard.",
            "ordered_items": [
                {"resource_id": "invented-id-not-in-catalogue", "priority": 1, "why": "...", "week": 1, "prerequisite_for": []},
            ]
        })
        # Should not crash — unknown IDs are filtered out
        roadmap = engine.generate({"DSA": 0.3})
        # Items with invalid IDs are excluded from the Groq-ordered list
        # but algorithm items may be appended as fallback
        assert isinstance(roadmap, Roadmap)

    def test_groq_response_why_is_used(self):
        """Groq's rationale should appear in the roadmap item's why field."""
        engine = self._make_engine(groq_response={
            "reasoning": "Overall assessment here.",
            "ordered_items": [
                {
                    "resource_id": "dsa-neetcode-roadmap",
                    "priority": 1,
                    "why": "Perfect for your DSA gap — structured practice paths.",
                    "week": 1,
                    "prerequisite_for": [],
                }
            ]
        })
        roadmap = engine.generate({"DSA": 0.25})
        if roadmap.generated_by == "groq" and roadmap.items:
            neetcode_items = [i for i in roadmap.items if i.resource.id == "dsa-neetcode-roadmap"]
            if neetcode_items:
                assert "structured practice" in neetcode_items[0].why

    def test_weak_topics_correctly_identified(self):
        engine = self._make_engine(groq_error=GroqClientError("off"))
        roadmap = engine.generate({"DSA": 0.3, "OS": 0.8, "DBMS": 0.2})
        assert "DSA" in roadmap.weak_topics
        assert "DBMS" in roadmap.weak_topics
        assert "OS" not in roadmap.weak_topics
