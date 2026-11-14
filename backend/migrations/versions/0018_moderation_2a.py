"""v3.3.44 后台批次 2a：评论处置（软删）、分享关闭与访问计数、理由模板、搜索词汇总

Revision ID: 0018
Revises: 0017
"""

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"

COLUMNS = {
    "comments": [
        sa.Column("handled_by", sa.Integer(), nullable=True),
        sa.Column("handled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("handle_reason", sa.String(300), nullable=False, server_default=""),
    ],
    "fav_folders": [
        sa.Column("share_closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("share_closed_by", sa.Integer(), nullable=True),
        sa.Column("share_closed_reason", sa.String(300), nullable=False, server_default=""),
        sa.Column("share_views", sa.Integer(), nullable=True),
    ],
}



def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    for table, cols in COLUMNS.items():
        have = {c["name"] for c in insp.get_columns(table)}
        with op.batch_alter_table(table) as b:
            for col in cols:
                if col.name not in have:
                    b.add_column(col)
    tables = insp.get_table_names()
    if "reason_templates" not in tables:
        op.create_table(
            "reason_templates",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("scope", sa.String(32), nullable=False),
            sa.Column("text", sa.String(300), nullable=False),
            sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_reason_templates_scope", "reason_templates", ["scope"])
    if "search_terms" not in tables:
        op.create_table(
            "search_terms",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("term", sa.String(100), nullable=False, unique=True),
            sa.Column("shown", sa.String(100), nullable=False, server_default=""),
            sa.Column("searches", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("empty_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_results", sa.Integer(), nullable=True),
            sa.Column("last_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("blocked", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("block_reason", sa.String(200), nullable=False, server_default=""),
            sa.Column("blocked_by", sa.Integer(), nullable=True),
            sa.Column("blocked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("covered_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("covered_by", sa.Integer(), nullable=True),
            sa.Column("covered_note", sa.String(200), nullable=False, server_default=""),
        )
        op.create_index("ix_search_terms_last_at", "search_terms", ["last_at"])
        op.create_index("ix_search_terms_blocked", "search_terms", ["blocked"])


def downgrade() -> None:
    op.drop_table("search_terms")
    op.drop_table("reason_templates")
    for table, cols in COLUMNS.items():
        with op.batch_alter_table(table) as b:
            for col in cols:
                b.drop_column(col.name)
