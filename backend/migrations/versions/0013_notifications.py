"""v3.3：站内消息、分类订阅、仓库 Release 记录

Revision ID: 0013
Revises: 0012
"""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())
    if "latest_release" not in {c["name"] for c in insp.get_columns("repos")}:
        op.add_column("repos", sa.Column("latest_release", sa.String(100), nullable=False, server_default=""))
    if "notifications" not in tables:
        op.create_table(
            "notifications",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("kind", sa.String(16), nullable=False),
            sa.Column("title", sa.String(200), nullable=False),
            sa.Column("body", sa.String(500), nullable=False, server_default=""),
            sa.Column("link", sa.String(300), nullable=False, server_default=""),
            sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
        op.create_index("ix_notifications_created_at", "notifications", ["created_at"])
    if "category_subscriptions" not in tables:
        op.create_table(
            "category_subscriptions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("category_id", sa.Integer(), sa.ForeignKey("categories.id", ondelete="CASCADE"), nullable=False),
            sa.Column("last_notified_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("user_id", "category_id"),
        )
        op.create_index("ix_category_subscriptions_user_id", "category_subscriptions", ["user_id"])
        op.create_index("ix_category_subscriptions_category_id", "category_subscriptions", ["category_id"])


def downgrade() -> None:
    op.drop_table("category_subscriptions")
    op.drop_table("notifications")
    op.drop_column("repos", "latest_release")
