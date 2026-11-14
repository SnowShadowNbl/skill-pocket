"""v3.3：评论内容审核（状态 + 审核说明）

Revision ID: 0010
Revises: 0009
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"


def upgrade() -> None:
    conn = op.get_bind()
    have = {c["name"] for c in sa.inspect(conn).get_columns("comments")}
    if "status" not in have:
        op.add_column("comments", sa.Column("status", sa.String(12), nullable=False, server_default="visible"))
        op.create_index("ix_comments_status", "comments", ["status"])
    if "review_reason" not in have:
        op.add_column("comments", sa.Column("review_reason", sa.String(200), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("comments", "review_reason")
    op.drop_index("ix_comments_status", "comments")
    op.drop_column("comments", "status")
