"""
ml/recommender/engine.py — Content-based recommendation engine

Pipeline:
  1. Score each skill's "gap" from mastery (1.0 - proficiency)
  2. Identify weak topics (gap > 0.5 OR score < threshold)
  3. For each weak topic, retrieve and rank matching resources
  4. Personalize with Groq — add prerequisites, study order, rationale
  5. Return a structured roadmap ready to store in the DB

WHY "gap from mastery" and not raw score?
  A user with DBMS=0.28 and DSA=0.72 has:
    DBMS gap = 0.72 → high priority
    DSA gap = 0.28 → lower priority
  Ranking by gap makes the recommendation "study what you're worst at first"
  rather than "study in alphabetical order."

  Nuance: DSA=0.72 might still warrant recommendations if the user explicitly
  requests DSA practice. We expose both threshold-based (automatic) and
  explicit (user-requested) modes.

WHY a 2-stage pipeline (algorithm + LLM) and not LLM alone?
  LLMs can hallucinate resources that don't exist or recommend poor-quality
  links. The algorithm provides a curated, verified resource pool.
  The LLM provides reasoning, ordering context, and personalization.
  Algorithm = relevance guarantee. LLM = intelligence layer.

  Real-world analogy: Spotify's recommendation is embedding-based similarity
  (algorithm) + editorial curation (human/LLM layer). Both are needed.
"""

import time
from dataclasses import dataclass, field

from recommender.catalogue import Resource, RESOURCE_CATALOGUE, get_resources_for_topic
from llm.groq_client import GroqClient, GroqClientError, get_groq_client

# ── Configuration ──────────────────────────────────────────────────────────────
WEAK_SKILL_THRESHOLD = 0.60   # Scores below this get recommendations
MAX_RESOURCES_PER_TOPIC = 2   # Prevent overwhelming the user
MAX_TOTAL_ITEMS = 8           # Cap the roadmap at 8 items

# Type weights — prefer varied resource types
# WHY? A roadmap of 8 articles is boring. Mix articles, practice, books.
TYPE_DIVERSITY_BONUS = {
    "article": 0.0,
    "practice": 0.05,    # Slight bonus for practice resources
    "course": 0.03,
    "book": 0.02,
    "video": 0.01,
}

# Difficulty weights by proficiency score
# If you score 0.2 (very weak), start with beginner resources
# If you score 0.4 (weak), intermediate is appropriate
DIFFICULTY_FOR_SCORE = {
    (0.0, 0.35): "beginner",
    (0.35, 0.60): "intermediate",
    (0.60, 1.0): "advanced",
}

RECOMMENDATION_SYSTEM_PROMPT = """You are an expert engineering mentor helping a developer prepare for technical interviews.

You will receive:
- A list of the user's weakest skills with scores (0.0 = knows nothing, 1.0 = expert)
- A list of recommended learning resources already matched to their weak areas

Your job is to:
1. Order the resources from most to least urgent (fix biggest weaknesses first)
2. Write a brief "why" rationale for each resource (1 sentence)
3. Identify if any topics are prerequisites for others and group accordingly
4. Estimate the week in which they should tackle each item (Week 1, Week 2, etc.)

IMPORTANT: Only use the resources provided. Do not invent new resources.

Respond ONLY with valid JSON:
{
  "reasoning": "2-sentence overall assessment of the user's weakest areas",
  "ordered_items": [
    {
      "resource_id": "the-resource-id",
      "priority": 1,
      "why": "One sentence explaining why this resource for this user",
      "week": 1,
      "prerequisite_for": ["topic1"] or []
    }
  ]
}"""


@dataclass
class RoadmapItem:
    """One item in the generated roadmap."""
    resource: Resource
    priority: int
    why: str              # LLM-generated rationale
    week: int             # Which week to tackle this
    skill_topic: str
    gap: float            # How weak the skill is (higher = more urgent)
    prerequisite_for: list[str] = field(default_factory=list)


@dataclass
class Roadmap:
    """The complete recommendation output."""
    items: list[RoadmapItem]
    reasoning: str        # LLM overall assessment
    weak_topics: list[str]
    generated_by: str     # "groq" | "algorithm"
    latency_ms: float


class RecommendationEngine:
    """
    Content-based recommendation engine with Groq personalization.
    """

    def __init__(self, groq_client: GroqClient = None):
        self._groq = groq_client

    def _groq_client(self) -> GroqClient:
        if self._groq is None:
            self._groq = get_groq_client()
        return self._groq

    def _compute_gaps(
        self, skill_scores: dict[str, float]
    ) -> list[tuple[str, float, float]]:
        """
        Compute gap from mastery for each skill.

        Returns list of (topic, score, gap) sorted by gap descending.
        Only includes topics below WEAK_SKILL_THRESHOLD.

        WHY sort by gap descending?
          The biggest gap = the most urgent improvement need.
          Studying your weakest area has the highest expected value —
          it moves the needle the most on your overall interview readiness.
        """
        gaps = []
        for topic, score in skill_scores.items():
            score = max(0.0, min(1.0, score))   # Clamp to [0, 1]
            gap = 1.0 - score
            if score < WEAK_SKILL_THRESHOLD:
                gaps.append((topic, score, gap))

        return sorted(gaps, key=lambda x: x[2], reverse=True)

    def _difficulty_for_score(self, score: float) -> str:
        """Map a proficiency score to appropriate resource difficulty."""
        for (low, high), difficulty in DIFFICULTY_FOR_SCORE.items():
            if low <= score < high:
                return difficulty
        return "intermediate"

    def _select_resources(
        self,
        topic: str,
        score: float,
        n: int = MAX_RESOURCES_PER_TOPIC,
    ) -> list[Resource]:
        """
        Select the best resources for a topic given the user's proficiency.

        Selection algorithm:
          1. Filter catalogue by topic
          2. Score each resource:
             - +0.3 if difficulty matches user's level
             - +type_diversity_bonus (prefer practice over articles)
             - +0.1 if resource is "starter" (beginner + low hours)
          3. Return top-n by score

        WHY not just return the first n resources?
          Resource quality and relevance varies within a topic.
          A user scoring 0.2 in DBMS should get beginner resources first.
          A user scoring 0.55 in DBMS should get intermediate resources.
          Difficulty matching is the key signal.
        """
        topic_resources = get_resources_for_topic(topic)
        if not topic_resources:
            return []

        target_difficulty = self._difficulty_for_score(score)

        scored = []
        for resource in topic_resources:
            relevance = 0.0

            # Difficulty match is the primary signal
            if resource.difficulty == target_difficulty:
                relevance += 0.30
            elif resource.difficulty == "beginner" and target_difficulty == "intermediate":
                relevance += 0.10   # Slight credit for easier resources as review
            elif resource.difficulty == "intermediate" and target_difficulty == "beginner":
                relevance += 0.05   # Don't overwhelm beginners with intermediate

            # Type diversity bonus
            relevance += TYPE_DIVERSITY_BONUS.get(resource.resource_type, 0.0)

            # Quick-win bonus: high-value, low time investment
            if resource.estimated_hours <= 2.0 and resource.difficulty == "beginner":
                relevance += 0.05

            scored.append((relevance, resource))

        # Sort by relevance score descending
        scored.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in scored[:n]]

    def _algorithm_only_roadmap(
        self, weak_topics: list[tuple[str, float, float]]
    ) -> list[dict]:
        """
        Pure algorithmic roadmap — no LLM, instant, deterministic.
        Used as Groq fallback and for testing.

        Returns flat list of resource dicts ready for LLM enrichment or direct use.
        """
        items = []
        priority = 1
        for topic, score, gap in weak_topics[:4]:   # Max 4 weak topics
            resources = self._select_resources(topic, score)
            for resource in resources:
                if len(items) >= MAX_TOTAL_ITEMS:
                    break
                items.append({
                    "resource_id": resource.id,
                    "resource": resource,
                    "topic": topic,
                    "score": score,
                    "gap": gap,
                    "priority": priority,
                    "why": f"Your {topic} score ({score:.0%}) is below target. "
                           f"This {resource.resource_type} addresses your key gaps.",
                    "week": ((priority - 1) // 2) + 1,
                    "prerequisite_for": [],
                })
                priority += 1

        return items

    def generate(
        self,
        skill_scores: dict[str, float],
        user_goal: str = "general interview preparation",
    ) -> Roadmap:
        """
        Generate a personalized learning roadmap.

        Args:
            skill_scores: Dict of {topic: proficiency_score} e.g. {"DSA": 0.34}
            user_goal: Context for personalization ("ML engineer", "backend role", etc)

        Returns:
            Roadmap with ordered items, rationale, and metadata
        """
        start = time.perf_counter()

        # Stage 1: Compute gaps and identify weak topics
        weak_gaps = self._compute_gaps(skill_scores)

        if not weak_gaps:
            # Keep the roadmap useful after a strong session.
            weak_gaps = sorted(
                (
                    (topic, max(0.0, min(1.0, score)), 1.0 - max(0.0, min(1.0, score)))
                    for topic, score in skill_scores.items()
                ),
                key=lambda item: item[2],
                reverse=True,
            )

        weak_topics = [topic for topic, _, _ in weak_gaps]

        # Stage 2: Select resources for each weak topic
        candidate_items = self._algorithm_only_roadmap(weak_gaps)

        if not candidate_items:
            return Roadmap(
                items=[],
                reasoning="No resources found for your weak topics.",
                weak_topics=weak_topics,
                generated_by="algorithm",
                latency_ms=0.0,
            )

        # Stage 3: Groq personalization
        groq = self._groq_client()
        if groq.is_available():
            try:
                roadmap = self._groq_personalize(
                    candidate_items, skill_scores, weak_gaps, user_goal
                )
                roadmap.latency_ms = round((time.perf_counter() - start) * 1000, 2)
                return roadmap
            except (GroqClientError, Exception) as e:
                # Fall back to algorithm-only
                pass

        # Algorithm-only fallback
        items = [
            RoadmapItem(
                resource=item["resource"],
                priority=item["priority"],
                why=item["why"],
                week=item["week"],
                skill_topic=item["topic"],
                gap=item["gap"],
            )
            for item in candidate_items
        ]

        return Roadmap(
            items=items,
            reasoning=f"Focus on your weakest areas: {', '.join(weak_topics[:3])}.",
            weak_topics=weak_topics,
            generated_by="algorithm",
            latency_ms=round((time.perf_counter() - start) * 1000, 2),
        )

    def _groq_personalize(
        self,
        candidate_items: list[dict],
        skill_scores: dict[str, float],
        weak_gaps: list[tuple[str, float, float]],
        user_goal: str,
    ) -> Roadmap:
        """
        Use Groq to intelligently order and rationalize the resource list.

        WHY give Groq the resources we already selected?
          We want Groq's reasoning, not its resource selection.
          Letting Groq pick resources risks hallucinated URLs.
          Letting Groq order curated resources is safe — it can only
          rearrange the list, not invent new items.

          This is "constrained generation" — LLM operates within boundaries
          set by the algorithm. The algorithm guarantees correctness;
          the LLM adds intelligence within those guarantees.
        """
        groq = self._groq_client()

        # Build the context for Groq
        weak_summary = "\n".join(
            f"- {topic}: score {score:.0%} (gap: {gap:.0%})"
            for topic, score, gap in weak_gaps[:4]
        )

        resource_list = "\n".join(
            f"- ID: {item['resource_id']}\n"
            f"  Title: {item['resource'].title}\n"
            f"  Type: {item['resource'].resource_type} ({item['resource'].difficulty})\n"
            f"  Topic: {item['topic']}\n"
            f"  Est. time: {item['resource'].estimated_hours}h\n"
            f"  Description: {item['resource'].description}"
            for item in candidate_items
        )

        user_message = f"""User Goal: {user_goal}

Weak Skills (sorted by urgency):
{weak_summary}

Available Learning Resources:
{resource_list}

Create a personalized study roadmap from these resources."""

        response = groq.complete(
            system_prompt=RECOMMENDATION_SYSTEM_PROMPT,
            user_message=user_message,
            temperature=0.3,
            max_tokens=600,
            json_mode=True,
        )

        # Build a lookup from resource_id → candidate item
        id_to_item = {item["resource_id"]: item for item in candidate_items}

        ordered_items = []
        for groq_item in response.get("ordered_items", []):
            resource_id = groq_item.get("resource_id", "")
            if resource_id not in id_to_item:
                continue   # Groq mentioned an ID we didn't provide — skip

            candidate = id_to_item[resource_id]
            ordered_items.append(RoadmapItem(
                resource=candidate["resource"],
                priority=groq_item.get("priority", len(ordered_items) + 1),
                why=groq_item.get("why", candidate["why"]),
                week=groq_item.get("week", 1),
                skill_topic=candidate["topic"],
                gap=candidate["gap"],
                prerequisite_for=groq_item.get("prerequisite_for", []),
            ))

        # If Groq returned fewer items than we have, append the rest
        groq_ids = {item.resource.id for item in ordered_items}
        for item in candidate_items:
            if item["resource_id"] not in groq_ids:
                ordered_items.append(RoadmapItem(
                    resource=item["resource"],
                    priority=len(ordered_items) + 1,
                    why=item["why"],
                    week=item["week"],
                    skill_topic=item["topic"],
                    gap=item["gap"],
                ))

        return Roadmap(
            items=ordered_items,
            reasoning=response.get("reasoning", "Personalized roadmap generated."),
            weak_topics=[topic for topic, _, _ in weak_gaps],
            generated_by="groq",
            latency_ms=0.0,  # Set by caller
        )


# ── Module singleton ───────────────────────────────────────────────────────────
_engine: RecommendationEngine = None

def get_recommendation_engine() -> RecommendationEngine:
    global _engine
    if _engine is None:
        _engine = RecommendationEngine()
    return _engine
