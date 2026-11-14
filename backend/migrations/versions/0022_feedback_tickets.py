"""v3.3.52 后台批次 4a：反馈工单（负责人、时间点、内部备注、回复模板）

Revision ID: 0022
Revises: 0021
"""

import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"

COLS = [
    sa.Column("assignee_id", sa.Integer(), nullable=True),
    sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("first_response_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
]


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    have = {c["name"] for c in insp.get_columns("feedback")}
    with op.batch_alter_table("feedback") as b:
        for col in COLS:
            if col.name not in have:
                b.add_column(col)
    if "ix_feedback_assignee_id" not in {i["name"] for i in insp.get_indexes("feedback")}:
        op.create_index("ix_feedback_assignee_id", "feedback", ["assignee_id"])
    # 老数据：已回复的把第一次回复时间当首次响应；已解决的用 updated_at 估算解决时间
    bind.execute(sa.text("UPDATE feedback SET first_response_at = replied_at WHERE first_response_at IS NULL AND replied_at IS NOT NULL"))
    bind.execute(sa.text("UPDATE feedback SET resolved_at = updated_at WHERE resolved_at IS NULL AND status = 'resolved'"))
    tables = insp.get_table_names()
    if "feedback_notes" not in tables:
        op.create_table(
            "feedback_notes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("feedback_id", sa.Integer(), sa.ForeignKey("feedback.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("text", sa.String(1000), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_feedback_notes_feedback_id", "feedback_notes", ["feedback_id"])
    if "reply_templates" not in tables:
        op.create_table(
            "reply_templates",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("scope", sa.String(32), nullable=False),
            sa.Column("title", sa.String(40), nullable=False),
            sa.Column("text", sa.String(500), nullable=False),
            sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_reply_templates_scope", "reply_templates", ["scope"])


def downgrade() -> None:
    op.drop_table("reply_templates")
    op.drop_table("feedback_notes")
    op.drop_index("ix_feedback_assignee_id", table_name="feedback")
    with op.batch_alter_table("feedback") as b:
        for col in COLS:
            b.drop_column(col.name)
