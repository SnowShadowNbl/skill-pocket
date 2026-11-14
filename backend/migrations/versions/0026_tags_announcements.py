"""v3.3.71 后台批次 7b：用户标签、小范围公告

Revision ID: 0026
Revises: 0025
"""

import sqlalchemy as sa
from alembic import op

revision = "0026"
down_revision = "0025"


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "announcement_id" not in {c["name"] for c in insp.get_columns("notifications")}:
        with op.batch_alter_table("notifications") as b:
            b.add_column(sa.Column("announcement_id", sa.Integer(), nullable=True))
        op.create_index("ix_notifications_announcement_id", "notifications", ["announcement_id"])
    tables = insp.get_table_names()
    if "tags" not in tables:
        op.create_table(
            "tags",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(30), nullable=False, unique=True),
            sa.Column("color", sa.String(16), nullable=False, server_default="blue"),
            sa.Column("description", sa.String(200), nullable=False, server_default=""),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "user_tags" not in tables:
        op.create_table(
            "user_tags",
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("tag_id", sa.Integer(), sa.ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_user_tags_tag_id", "user_tags", ["tag_id"])
    if "announcements" not in tables:
        op.create_table(
            "announcements",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("title", sa.String(40), nullable=False),
            sa.Column("text", sa.String(500), nullable=False),
            sa.Column("link", sa.String(300), nullable=False, server_default=""),
            sa.Column("audience", sa.JSON(), nullable=True),
            sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
            sa.Column("recipients", sa.Integer(), nullable=True),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("sent_by", sa.Integer(), nullable=True),
            sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_announcements_status", "announcements", ["status"])


def downgrade() -> None:
    op.drop_table("announcements")
    op.drop_table("user_tags")
    op.drop_table("tags")
    op.drop_index("ix_notifications_announcement_id", table_name="notifications")
    with op.batch_alter_table("notifications") as b:
        b.drop_column("announcement_id")
