"""v3.3.50 后台批次 3c：分类合并重定向、AI 分类抽检

Revision ID: 0021
Revises: 0020
"""

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "merged_into_id" not in {c["name"] for c in insp.get_columns("categories")}:
        with op.batch_alter_table("categories") as b:
            b.add_column(sa.Column("merged_into_id", sa.Integer(), nullable=True))
    if "category_audits" not in insp.get_table_names():
        op.create_table(
            "category_audits",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("task_id", sa.Integer(), nullable=True),
            sa.Column("item_id", sa.Integer(), sa.ForeignKey("items.id", ondelete="CASCADE"), nullable=True),
            sa.Column("current_id", sa.Integer(), nullable=True),
            sa.Column("suggested_id", sa.Integer(), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("reason", sa.String(300), nullable=False, server_default=""),
            sa.Column("agree", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("status", sa.String(16), nullable=False, server_default="open"),
            sa.Column("decided_by", sa.Integer(), nullable=True),
            sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("decision_reason", sa.String(300), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        )
        for col in ("task_id", "item_id", "status", "created_at"):
            op.create_index(f"ix_category_audits_{col}", "category_audits", [col])


def downgrade() -> None:
    op.drop_table("category_audits")
    with op.batch_alter_table("categories") as b:
        b.drop_column("merged_into_id")
