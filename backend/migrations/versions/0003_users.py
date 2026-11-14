"""v2.0-α：用户体系（用户、登录会话、邮箱验证码、发信记录），各业务表关联用户；现有数据归给 admin

Revision ID: 0003
Revises: 0002
"""

from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"

TS = sa.DateTime(timezone=True)
USER_COLUMNS = ("items", "comments", "uploads", "tasks", "ingest_logs", "finder_jobs")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(254), unique=True, nullable=True),
        sa.Column("username", sa.String(40), unique=True, nullable=True),
        sa.Column("nickname", sa.String(40), nullable=False),
        sa.Column("avatar", sa.String(40), nullable=False),
        sa.Column("password_hash", sa.String(100), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, index=True),
        sa.Column("created_at", TS, nullable=False, index=True),
        sa.Column("last_login_at", TS, nullable=True),
    )
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("token_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("device", sa.String(120), nullable=False),
        sa.Column("ip", sa.String(64), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("last_seen_at", TS, nullable=False),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("revoked_at", TS, nullable=True),
    )
    op.create_table(
        "email_codes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(254), nullable=False, index=True),
        sa.Column("purpose", sa.String(16), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("ip", sa.String(64), nullable=False),
        sa.Column("created_at", TS, nullable=False, index=True),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("used_at", TS, nullable=True),
    )
    op.create_table(
        "email_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(254), nullable=False, index=True),
        sa.Column("purpose", sa.String(16), nullable=False),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("created_at", TS, nullable=False, index=True),
    )

    for table in USER_COLUMNS:
        col = "created_by" if table == "items" else "user_id"
        with op.batch_alter_table(table) as b:
            b.add_column(sa.Column(col, sa.Integer(), nullable=True))
            b.create_foreign_key(f"fk_{table}_{col}_users", "users", [col], ["id"], ondelete="SET NULL")
            b.create_index(f"ix_{table}_{col}", [col])

    # 唯一的超级管理员：沿用 v1.x 的管理员密码，用户名 admin
    from app.config import settings

    users = sa.table(
        "users", sa.column("id", sa.Integer), sa.column("username", sa.String), sa.column("nickname", sa.String),
        sa.column("avatar", sa.String), sa.column("password_hash", sa.String), sa.column("role", sa.String),
        sa.column("status", sa.String), sa.column("created_at", TS),
    )
    op.bulk_insert(users, [{
        "username": "admin", "nickname": "管理员", "avatar": "", "password_hash": settings.admin_password_hash or "",
        "role": "admin", "status": "active", "created_at": datetime.now(timezone.utc),
    }])
    admin_id = "(SELECT id FROM users WHERE username = 'admin')"
    # v1.3 全站共用的收藏与收藏分类、手动上传的条目，都归给 admin
    op.execute(f"UPDATE favorites SET owner_id = {admin_id} WHERE owner_id = 0")
    op.execute(f"UPDATE fav_dimensions SET owner_id = {admin_id} WHERE owner_id = 0")
    op.execute(f"UPDATE items SET created_by = {admin_id} WHERE source = 'manual'")


def downgrade() -> None:
    op.execute("UPDATE favorites SET owner_id = 0")
    op.execute("UPDATE fav_dimensions SET owner_id = 0")
    for table in USER_COLUMNS:
        col = "created_by" if table == "items" else "user_id"
        with op.batch_alter_table(table) as b:
            b.drop_index(f"ix_{table}_{col}")
            b.drop_constraint(f"fk_{table}_{col}_users", type_="foreignkey")
            b.drop_column(col)
    for t in ("email_logs", "email_codes", "auth_sessions", "users"):
        op.drop_table(t)
