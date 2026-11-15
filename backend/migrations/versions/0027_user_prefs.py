"""v3.3.85 小程序简洁模式：账号偏好（首页模式、搜索历史）

Revision ID: 0027
Revises: 0026
"""

import sqlalchemy as sa
from alembic import op

revision = "0027"
down_revision = "0026"


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "prefs" not in {c["name"] for c in insp.get_columns("users")}:
        with op.batch_alter_table("users") as b:
            b.add_column(sa.Column("prefs", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as b:
        b.drop_column("prefs")
