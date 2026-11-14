"""v2.1：游客识别与行为埋点（visitors / events / event_daily）

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "visitors",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("first_seen", TS, nullable=False, index=True),
        sa.Column("last_seen", TS, nullable=False, index=True),
        sa.Column("first_ip", sa.String(64), nullable=False),
        sa.Column("last_ip", sa.String(64), nullable=False),
        sa.Column("first_geo", sa.String(80), nullable=False),
        sa.Column("last_geo", sa.String(80), nullable=False, index=True),
        sa.Column("device", sa.String(60), nullable=False),
        sa.Column("referrer", sa.String(300), nullable=False),
        sa.Column("landing", sa.String(300), nullable=False),
        sa.Column("visits", sa.Integer(), nullable=False),
        sa.Column("events", sa.Integer(), nullable=False),
        sa.Column("converted_at", TS, nullable=True),
    )
    op.create_table(
        "events",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True, autoincrement=True),
        sa.Column("vid", sa.String(40), nullable=False, index=True),
        sa.Column("user_id", sa.Integer(), nullable=True, index=True),
        sa.Column("name", sa.String(40), nullable=False, index=True),
        sa.Column("category", sa.String(16), nullable=False, index=True),
        sa.Column("props", sa.JSON(), nullable=False),
        sa.Column("page", sa.String(300), nullable=False),
        sa.Column("ip", sa.String(64), nullable=False),
        sa.Column("geo", sa.String(80), nullable=False),
        sa.Column("created_at", TS, nullable=False, index=True),
    )
    op.create_table(
        "event_daily",
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("name", sa.String(40), primary_key=True),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("uv", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    for t in ("event_daily", "events", "visitors"):
        op.drop_table(t)
