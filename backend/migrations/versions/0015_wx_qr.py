"""v3.3.9：网页微信扫码登录 / 绑定（小程序码）

Revision ID: 0015
Revises: 0014
"""

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"


def upgrade() -> None:
    if "wx_qr_logins" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "wx_qr_logins",
        sa.Column("token", sa.String(32), primary_key=True),
        sa.Column("purpose", sa.String(8), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="pending"),
        sa.Column("web_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("wx_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("wx_qr_logins")
