"""
backend/app/services/recommendation_service.py

Orchestrates the full recommendation flow:
  1. Fetch user's skill assessments from DB
  2. Check Redis cache (roadmap cached for 1 hour)
  3. If cache miss: call ML service /recommend
  4. Store roadmap items in DB
  5. Cache in Redis
  6. Return to the endpoint
"""

import uuid
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.submission import SkillAssessment, RoadmapItem
from app.services.cache_service import CacheService
from app.services.ml_client import MLClient, get_ml_client


class RecommendationService:
    def __init__(self, db: AsyncSession, cache: CacheService, ml: MLClient = None):
        self.db = db
        self.cache = cache
        self.ml = ml or get_ml_client()

    async def get_or_generate_roadmap(
        self,
        user_id: uuid.UUID,
        user_goal: str = "general interview preparation",
        force_refresh: bool = False,
    ) -> list[dict]:
        """
        Get the user's roadmap, generating it if needed.

        Cache strategy:
          - Cache key: roadmap:{user_id}
          - TTL: 3600s (1 hour)
          - Invalidated when: skill assessments are updated
          - force_refresh: bypass cache (e.g., user clicks "Regenerate Roadmap")

        WHY store roadmap in BOTH Redis AND PostgreSQL?
          Redis: fast reads for the frontend dashboard
          PostgreSQL: persistent storage, tracks completion status
          If Redis evicts the key, the DB is the source of truth.
        """
        # Check cache first (unless force_refresh)
        if not force_refresh:
            cached = await self.cache.get_roadmap(user_id)
            if cached and all("id" in item and "skill_topic" in item for item in cached):
                return cached

        # Fetch current skill assessments
        result = await self.db.execute(
            select(SkillAssessment).where(SkillAssessment.user_id == user_id)
        )
        assessments = result.scalars().all()

        if not assessments:
            return []

        skill_scores = {
            a.skill_topic: a.proficiency_score
            for a in assessments
        }

        # Call ML service
        try:
            ml_response = await self.ml.recommend(skill_scores, user_goal)
        except Exception:
            # ML service unavailable — return cached DB roadmap if it exists
            return await self._get_from_db(user_id)

        # Persist roadmap items to DB
        await self._persist_roadmap(user_id, ml_response.get("items", []))

        # Cache the public DB representation expected by the API.
        serializable = await self._get_from_db(user_id)
        if serializable:
            await self.cache.set_roadmap(user_id, serializable)

        return serializable

    async def _persist_roadmap(
        self, user_id: uuid.UUID, items: list[dict]
    ) -> None:
        """
        Replace the user's roadmap items in the DB.

        WHY delete and re-insert instead of upsert?
          The ML service generates a fresh ordered list.
          Upserting requires matching on (user_id, resource_id) and
          handling priority/order changes. Delete+insert is simpler and
          more correct — the new roadmap fully replaces the old one.
          We preserve completion status by checking existing items first.

          Production consideration: wrap in a transaction so the user
          never sees a partially-updated roadmap.
        """
        # Fetch existing completion status before replacing
        existing = await self.db.execute(
            select(RoadmapItem).where(RoadmapItem.user_id == user_id)
        )
        completed_ids = {
            item.resource_url: item.completed
            for item in existing.scalars().all()
        }

        # Delete old items
        await self.db.execute(
            delete(RoadmapItem).where(RoadmapItem.user_id == user_id)
        )

        # Insert new items — preserving completion status
        for item in items:
            url = item.get("url", "")
            db_item = RoadmapItem(
                user_id=user_id,
                skill_topic=item.get("topic", ""),
                resource_title=item.get("title", ""),
                resource_url=url,
                resource_type=item.get("resource_type", "article"),
                priority=item.get("priority", 1),
                completed=completed_ids.get(url, False),   # Preserve completion
            )
            self.db.add(db_item)

        await self.db.flush()

    async def _get_from_db(self, user_id: uuid.UUID) -> list[dict]:
        """Fallback: load roadmap from DB when ML service is unavailable."""
        result = await self.db.execute(
            select(RoadmapItem)
            .where(RoadmapItem.user_id == user_id)
            .order_by(RoadmapItem.priority)
        )
        return [
            {
                "id": str(item.id),
                "skill_topic": item.skill_topic,
                "resource_title": item.resource_title,
                "resource_url": item.resource_url,
                "resource_type": item.resource_type,
                "priority": item.priority,
                "completed": item.completed,
            }
            for item in result.scalars().all()
        ]
