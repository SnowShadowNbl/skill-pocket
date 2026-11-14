"""v2.4：条目图片集（items.images）、IP 封禁（ip_bans）

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.add_column("items", sa.Column("images", sa.JSON(), nullable=True))
    # 已有封面的条目，图片集先只有这一张
    items = sa.table("items", sa.column("id", sa.Integer), sa.column("cover_path", sa.String), sa.column("images", sa.JSON))
    conn = op.get_bind()
    for iid, cover in conn.execute(sa.select(items.c.id, items.c.cover_path)).all():
        conn.execute(items.update().where(items.c.id == iid).values(images=[cover] if cover else []))
    op.create_table(
        "ip_bans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cidr", sa.String(64), nullable=False, unique=True),
        sa.Column("reason", sa.String(200), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("expires_at", TS, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("ip_bans")
    op.drop_column("items", "images")
