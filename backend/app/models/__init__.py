"""
Import all models here so SQLAlchemy's relationship registry is fully populated
before any mapper configuration runs.

WHY this matters:
  SQLAlchemy uses string-based forward references for relationships
  (e.g., relationship("InterviewSession")).
  When Python resolves "InterviewSession", the class must already be imported.
  Importing models in __init__.py guarantees the full graph is loaded together.
"""
from app.models.user import User  # noqa: F401
from app.models.session import InterviewSession, SessionQuestion  # noqa: F401
from app.models.submission import Submission, SkillAssessment, RoadmapItem  # noqa: F401
