"""v3.3.37 后台批次 0：操作日志留痕字段；注册渠道、登录端 / 版本 / 方式；事件的端

Revision ID: 0016
Revises: 0015
"""

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"

COLUMNS = {
    "activity_logs": [
        sa.Column("reason", sa.String(300), nullable=False, server_default=""),
        sa.Column("before", sa.JSON(), nullable=True),
        sa.Column("after", sa.JSON(), nullable=True),
        sa.Column("result", sa.String(16), nullable=False, server_default="ok"),
        sa.Column("message", sa.String(300), nullable=False, server_default=""),
        sa.Column("target_label", sa.String(200), nullable=False, server_default=""),
    ],
    "users": [
        sa.Column("signup_channel", sa.String(16), nullable=False, server_default=""),
        sa.Column("last_client", sa.String(16), nullable=False, server_default=""),
        sa.Column("last_client_version", sa.String(40), nullable=False, server_default=""),
    ],
    "auth_sessions": [
        sa.Column("client", sa.String(16), nullable=False, server_default=""),
        sa.Column("client_version", sa.String(40), nullable=False, server_default=""),
        sa.Column("method", sa.String(16), nullable=False, server_default=""),
    ],
    "events": [
        sa.Column("client", sa.String(16), nullable=False, server_default=""),
    ],
}


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    for table, cols in COLUMNS.items():
        have = {c["name"] for c in insp.get_columns(table)}
        with op.batch_alter_table(table) as b:
            for col in cols:
                if col.name not in have:
                    b.add_column(col)
    if "ix_events_client" not in {i["name"] for i in insp.get_indexes("events")}:
        op.create_index("ix_events_client", "events", ["client"])


def downgrade() -> None:
    op.drop_index("ix_events_client", table_name="events")
    for table, cols in COLUMNS.items():
        with op.batch_alter_table(table) as b:
            for col in cols:
                b.drop_column(col.name)
