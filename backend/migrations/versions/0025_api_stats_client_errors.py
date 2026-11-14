"""v3.3.66 后台批次 6c：接口请求小时汇总、客户端报错

Revision ID: 0025
Revises: 0024
"""

import sqlalchemy as sa
from alembic import op

revision = "0025"
down_revision = "0024"


def upgrade() -> None:
    tables = sa.inspect(op.get_bind()).get_table_names()
    if "api_stats" not in tables:
        op.create_table(
            "api_stats",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("hour", sa.DateTime(timezone=True), nullable=False),
            sa.Column("method", sa.String(8), nullable=False),
            sa.Column("path", sa.String(200), nullable=False),
            sa.Column("requests", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("errors_4xx", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("errors_5xx", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("total_ms", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column("max_ms", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("buckets", sa.JSON(), nullable=True),
            sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_status", sa.Integer(), nullable=True),
            sa.UniqueConstraint("hour", "method", "path", name="uq_api_stat"),
        )
        op.create_index("ix_api_stats_hour", "api_stats", ["hour"])
    if "client_errors" not in tables:
        op.create_table(
            "client_errors",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("fingerprint", sa.String(64), nullable=False, unique=True),
            sa.Column("client", sa.String(16), nullable=False, server_default=""),
            sa.Column("version", sa.String(40), nullable=False, server_default=""),
            sa.Column("kind", sa.String(16), nullable=False, server_default="js_error"),
            sa.Column("page", sa.String(300), nullable=False, server_default=""),
            sa.Column("message", sa.String(500), nullable=False, server_default=""),
            sa.Column("stack", sa.Text(), nullable=False, server_default=""),
            sa.Column("count", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("users", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("first_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_user_id", sa.Integer(), nullable=True),
            sa.Column("user_agent", sa.String(300), nullable=False, server_default=""),
        )
        for col in ("client", "version", "last_at", "last_user_id"):
            op.create_index(f"ix_client_errors_{col}", "client_errors", [col])


def downgrade() -> None:
    op.drop_table("client_errors")
    op.drop_table("api_stats")
