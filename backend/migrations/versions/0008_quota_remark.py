"""v2.6：AI 额度（按账号计 token、充值与调整记录、每日用量）、管理员备注名

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"

TS = sa.DateTime(timezone=True)
BIG = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    have = lambda t: {c["name"] for c in insp.get_columns(t)}  # noqa: E731 — SQLite 的 DDL 不在事务里，失败重跑时跳过已加的列
    sqlite = conn.dialect.name == "sqlite"
    if "remark" not in have("users"):
        op.add_column("users", sa.Column("remark", sa.String(60), nullable=False, server_default=""))
    if "quota_balance" not in have("users"):
        op.add_column("users", sa.Column("quota_balance", sa.BigInteger(), nullable=True))
    if "user_id" not in have("ai_calls"):
        # SQLite 不支持 ALTER 加外键（只在本地开发用），PostgreSQL 照常带外键
        fk = [] if sqlite else [sa.ForeignKey("users.id", ondelete="SET NULL")]
        op.add_column("ai_calls", sa.Column("user_id", sa.Integer(), *fk, nullable=True))
        op.create_index("ix_ai_calls_user_id", "ai_calls", ["user_id"])
    op.create_table(
        "quota_ledger",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("delta", sa.BigInteger(), nullable=False),
        sa.Column("balance_after", sa.BigInteger(), nullable=False),
        sa.Column("amount_yuan", sa.Float(), nullable=True),
        sa.Column("note", sa.String(200), nullable=False, server_default=""),
        sa.Column("operator_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", TS, nullable=False, index=True),
    )
    op.create_table(
        "quota_daily",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("day", sa.Date(), nullable=False, index=True),
        sa.Column("calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("used", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("balance_end", sa.BigInteger(), nullable=False, server_default="0"),
        sa.UniqueConstraint("user_id", "day", name="uq_quota_daily"),
    )


def downgrade() -> None:
    op.drop_table("quota_daily")
    op.drop_table("quota_ledger")
    op.drop_index("ix_ai_calls_user_id", "ai_calls")
    op.drop_column("ai_calls", "user_id")
    op.drop_column("users", "quota_balance")
    op.drop_column("users", "remark")
