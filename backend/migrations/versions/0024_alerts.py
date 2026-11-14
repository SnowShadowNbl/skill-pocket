"""v3.3.64 后台批次 6a：告警历史

Revision ID: 0024
Revises: 0023
"""

import sqlalchemy as sa
from alembic import op

revision = "0024"
down_revision = "0023"


def upgrade() -> None:
    if "alerts" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("source", sa.String(16), nullable=False, server_default="system"),
        sa.Column("level", sa.String(16), nullable=False, server_default="warn"),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False, server_default=""),
        sa.Column("count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("first_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("acked_by", sa.Integer(), nullable=True),
        sa.Column("acked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.Integer(), nullable=True),
        sa.Column("resolved_auto", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
    )
    for col in ("key", "source", "last_at", "status"):
        op.create_index(f"ix_alerts_{col}", "alerts", [col])


def downgrade() -> None:
    op.drop_table("alerts")
