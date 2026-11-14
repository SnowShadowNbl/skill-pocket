"""v3.3.42 后台批次 1：管理员保存的筛选视图

Revision ID: 0017
Revises: 0016
"""

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"


def upgrade() -> None:
    if "admin_views" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "admin_views",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("name", sa.String(40), nullable=False),
        sa.Column("query", sa.JSON(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("user_id", "scope", "name", name="uq_admin_view_name"),
    )
    op.create_index("ix_admin_views_user_id", "admin_views", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_admin_views_user_id", table_name="admin_views")
    op.drop_table("admin_views")
