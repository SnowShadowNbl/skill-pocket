"""v3.3：收藏分类公开分享（share_token）

Revision ID: 0012
Revises: 0011
"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"


def upgrade() -> None:
    have = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("fav_folders")}
    if "share_token" not in have:
        op.add_column("fav_folders", sa.Column("share_token", sa.String(24), nullable=True))
        op.create_index("ix_fav_folders_share_token", "fav_folders", ["share_token"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_fav_folders_share_token", "fav_folders")
    op.drop_column("fav_folders", "share_token")
