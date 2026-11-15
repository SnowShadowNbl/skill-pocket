"""v3.3.89 额度用完弹窗与成本核算：ai_calls 记录调用当时的真实成本快照

Revision ID: 0028
Revises: 0027
"""

import sqlalchemy as sa
from alembic import op

revision = "0028"
down_revision = "0027"

COLS = (("cache_hit_tokens", sa.Integer()), ("cost_max_yuan", sa.Float()), ("cost_actual_yuan", sa.Float()))


def upgrade() -> None:
    have = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("ai_calls")}
    with op.batch_alter_table("ai_calls") as b:
        for name, typ in COLS:
            if name not in have:
                b.add_column(sa.Column(name, typ, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("ai_calls") as b:
        for name, _ in COLS:
            b.drop_column(name)
