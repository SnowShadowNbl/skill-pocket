"""v2.0：用户提交审核、上线日志、操作日志、用户反馈、语义搜索向量、失效巡检

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    with op.batch_alter_table("items") as b:
        b.add_column(sa.Column("review_state", sa.String(16), nullable=False, server_default=""))
        b.add_column(sa.Column("search_tags", sa.JSON(), nullable=True))
        b.add_column(sa.Column("offline_at", TS, nullable=True))
        b.add_column(sa.Column("offline_reason", sa.String(200), nullable=False, server_default=""))
        b.add_column(sa.Column("checked_at", TS, nullable=True))
        b.create_index("ix_items_review_state", ["review_state"])

    op.create_table(
        "item_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("item_id", sa.Integer(), sa.ForeignKey("items.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("item_name", sa.String(200), nullable=False),
        sa.Column("submitter_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("reviewer", sa.String(16), nullable=False),
        sa.Column("reviewer_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("created_at", TS, nullable=False, index=True),
    )
    op.create_table(
        "activity_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("actor", sa.String(16), nullable=False),
        sa.Column("action", sa.String(40), nullable=False, index=True),
        sa.Column("target_type", sa.String(20), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=True),
        sa.Column("summary", sa.String(300), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.Column("ip", sa.String(64), nullable=False),
        sa.Column("created_at", TS, nullable=False, index=True),
    )
    op.create_table(
        "feedback",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("contact_email", sa.String(254), nullable=False),
        sa.Column("category", sa.String(16), nullable=False, index=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("input_type", sa.String(8), nullable=False),
        sa.Column("images", sa.JSON(), nullable=False),
        sa.Column("diagnostics", sa.JSON(), nullable=False),
        sa.Column("item_id", sa.Integer(), sa.ForeignKey("items.id", ondelete="SET NULL"), nullable=True),
        sa.Column("page_url", sa.String(500), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, index=True),
        sa.Column("priority", sa.String(4), nullable=False, index=True),
        sa.Column("ai_status", sa.String(16), nullable=False),
        sa.Column("ai_analysis", sa.JSON(), nullable=False),
        sa.Column("admin_reply", sa.Text(), nullable=False),
        sa.Column("replied_at", TS, nullable=True),
        sa.Column("user_unread", sa.Boolean(), nullable=False),
        sa.Column("created_at", TS, nullable=False, index=True),
        sa.Column("updated_at", TS, nullable=False),
    )
    op.create_table(
        "item_embeddings",
        sa.Column("item_id", sa.Integer(), sa.ForeignKey("items.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("dims", sa.Integer(), nullable=False),
        sa.Column("vector", sa.JSON(), nullable=False),
        sa.Column("basis_hash", sa.String(64), nullable=False),
        sa.Column("updated_at", TS, nullable=False),
    )
    op.create_table(
        "liveness_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("started_at", TS, nullable=False, index=True),
        sa.Column("finished_at", TS, nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("checked", sa.Integer(), nullable=False),
        sa.Column("went_offline", sa.Integer(), nullable=False),
        sa.Column("restored", sa.Integer(), nullable=False),
        sa.Column("errors", sa.Integer(), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False),
    )


def downgrade() -> None:
    for t in ("liveness_runs", "item_embeddings", "feedback", "activity_logs", "item_reviews"):
        op.drop_table(t)
    with op.batch_alter_table("items") as b:
        b.drop_index("ix_items_review_state")
        for c in ("checked_at", "offline_reason", "offline_at", "search_tags", "review_state"):
            b.drop_column(c)
