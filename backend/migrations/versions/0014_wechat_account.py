"""v3.3.9 小程序账号：users 加微信登录与账号合并字段（只加不改，现有用户全部为空值）

Revision ID: 0014
Revises: 0013
"""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"


def upgrade() -> None:
    conn = op.get_bind()
    have = {c["name"] for c in sa.inspect(conn).get_columns("users")}  # 失败重跑时跳过已加的列
    with op.batch_alter_table("users") as b:
        if "wx_openid" not in have:
            b.add_column(sa.Column("wx_openid", sa.String(64), nullable=True))
        if "wx_unionid" not in have:
            b.add_column(sa.Column("wx_unionid", sa.String(64), nullable=True))
        if "merged_into" not in have:
            b.add_column(sa.Column("merged_into", sa.Integer(), nullable=True))
            b.create_foreign_key("fk_users_merged_into", "users", ["merged_into"], ["id"], ondelete="SET NULL")
    idx = {i["name"] for i in sa.inspect(conn).get_indexes("users")}
    if "ix_users_wx_openid" not in idx:
        op.create_index("ix_users_wx_openid", "users", ["wx_openid"], unique=True)
    if "ix_users_wx_unionid" not in idx:
        op.create_index("ix_users_wx_unionid", "users", ["wx_unionid"])


def downgrade() -> None:
    op.drop_index("ix_users_wx_unionid", "users")
    op.drop_index("ix_users_wx_openid", "users")
    with op.batch_alter_table("users") as b:
        b.drop_constraint("fk_users_merged_into", type_="foreignkey")
        b.drop_column("merged_into")
        b.drop_column("wx_unionid")
        b.drop_column("wx_openid")
