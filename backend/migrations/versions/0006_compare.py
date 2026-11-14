"""v2.3：对比（compare_runs）

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "compare_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(64), nullable=False, index=True),
        sa.Column("entries", sa.JSON(), nullable=False),
        sa.Column("subjects", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("stage", sa.String(200), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("error", sa.String(300), nullable=False),
        sa.Column("model", sa.String(80), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("created_at", TS, nullable=False, index=True),
        sa.Column("finished_at", TS, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("compare_runs")
