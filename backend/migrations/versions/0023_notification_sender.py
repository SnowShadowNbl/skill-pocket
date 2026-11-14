"""v3.3.57 后台批次 4c：站内消息记录发送人（管理员单发）

Revision ID: 0023
Revises: 0022
"""

import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "sender_id" not in {c["name"] for c in insp.get_columns("notifications")}:
        with op.batch_alter_table("notifications") as b:
            b.add_column(sa.Column("sender_id", sa.Integer(), nullable=True))
        op.create_index("ix_notifications_sender_id", "notifications", ["sender_id"])


def downgrade() -> None:
    op.drop_index("ix_notifications_sender_id", table_name="notifications")
    with op.batch_alter_table("notifications") as b:
        b.drop_column("sender_id")
