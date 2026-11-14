"""v3.0.1：首页置顶权重、反馈回复记录（可带图片）

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    have = lambda t: {c["name"] for c in insp.get_columns(t)}  # noqa: E731 — 失败重跑时跳过已加的列
    if "pin_weight" not in have("items"):
        op.add_column("items", sa.Column("pin_weight", sa.Integer(), nullable=False, server_default="0"))
        op.create_index("ix_items_pin_weight", "items", ["pin_weight"])
    if "replies" not in have("feedback"):
        op.add_column("feedback", sa.Column("replies", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("feedback", "replies")
    op.drop_index("ix_items_pin_weight", "items")
    op.drop_column("items", "pin_weight")
