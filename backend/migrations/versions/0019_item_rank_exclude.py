"""v3.3.46 后台批次 3a：条目排除出榜单

Revision ID: 0019
Revises: 0018
"""

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"

COLS = [
    sa.Column("rank_excluded", sa.Boolean(), nullable=False, server_default=sa.false()),
    sa.Column("rank_exclude_reason", sa.String(300), nullable=False, server_default=""),
    sa.Column("rank_excluded_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("rank_excluded_by", sa.Integer(), nullable=True),
]


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    have = {c["name"] for c in insp.get_columns("items")}
    with op.batch_alter_table("items") as b:
        for col in COLS:
            if col.name not in have:
                b.add_column(col)
    if "ix_items_rank_excluded" not in {i["name"] for i in insp.get_indexes("items")}:
        op.create_index("ix_items_rank_excluded", "items", ["rank_excluded"])


def downgrade() -> None:
    op.drop_index("ix_items_rank_excluded", table_name="items")
    with op.batch_alter_table("items") as b:
        for col in COLS:
            b.drop_column(col.name)
