"""adaptive question metadata

Revision ID: 0002
Revises: 0001
"""

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("session_questions", sa.Column("question_bank_id", sa.String(100), nullable=True))
    op.add_column("session_questions", sa.Column("skill_tag", sa.String(50), nullable=True))
    op.add_column("session_questions", sa.Column("difficulty", sa.String(10), nullable=True))
    op.create_index(
        "ix_session_questions_question_bank_id",
        "session_questions",
        ["question_bank_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_session_questions_question_bank_id", table_name="session_questions")
    op.drop_column("session_questions", "difficulty")
    op.drop_column("session_questions", "skill_tag")
    op.drop_column("session_questions", "question_bank_id")
