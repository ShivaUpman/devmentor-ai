"""schemas/roadmap.py — Pydantic schemas for Roadmap and Skill Assessments"""

import uuid
from datetime import datetime

from pydantic import BaseModel


class SkillAssessmentResponse(BaseModel):
    skill_topic: str
    proficiency_score: float
    attempts: int
    last_assessed_at: datetime
    model_config = {"from_attributes": True}


class RoadmapItemResponse(BaseModel):
    id: uuid.UUID
    skill_topic: str
    resource_title: str
    resource_url: str
    resource_type: str
    priority: int
    completed: bool
    model_config = {"from_attributes": True}


class RoadmapItemUpdate(BaseModel):
    completed: bool
