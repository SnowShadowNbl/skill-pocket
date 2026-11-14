"""v3.3：好用度评分（评论打分 + 条目口碑缓存）

Revision ID: 0011
Revises: 0010
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    have = lambda t: {c["name"] for c in insp.get_columns(t)}  # noqa: E731
    if "rating" not in have("comments"):
        op.add_column("comments", sa.Column("rating", sa.Integer(), nullable=True))
    if "rating_avg" not in have("items"):
        op.add_column("items", sa.Column("rating_avg", sa.Float(), nullable=True))
    if "rating_count" not in have("items"):
        op.add_column("items", sa.Column("rating_count", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("items", "rating_count")
    op.drop_column("items", "rating_avg")
    op.drop_column("comments", "rating")
