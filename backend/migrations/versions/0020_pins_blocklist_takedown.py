"""v3.3.48 后台批次 3b：推荐位排期、黑名单、下架申请

Revision ID: 0020
Revises: 0019
"""

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    have = {c["name"] for c in insp.get_columns("items")}
    with op.batch_alter_table("items") as b:
        for name in ("pin_starts_at", "pin_ends_at"):
            if name not in have:
                b.add_column(sa.Column(name, sa.DateTime(timezone=True), nullable=True))
    tables = insp.get_table_names()
    if "block_entries" not in tables:
        op.create_table(
            "block_entries",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("kind", sa.String(16), nullable=False),
            sa.Column("value", sa.String(200), nullable=False),
            sa.Column("reason", sa.String(300), nullable=False, server_default=""),
            sa.Column("source", sa.String(16), nullable=False, server_default="manual"),
            sa.Column("takedown_id", sa.Integer(), nullable=True),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("kind", "value", name="uq_block_entry"),
        )
    if "takedown_requests" not in tables:
        op.create_table(
            "takedown_requests",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("item_id", sa.Integer(), sa.ForeignKey("items.id", ondelete="SET NULL"), nullable=True),
            sa.Column("item_name", sa.String(200), nullable=False, server_default=""),
            sa.Column("repo_full_name", sa.String(200), nullable=False, server_default=""),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("relation", sa.String(16), nullable=False, server_default="author"),
            sa.Column("reason", sa.Text(), nullable=False, server_default=""),
            sa.Column("contact", sa.String(200), nullable=False, server_default=""),
            sa.Column("evidence_url", sa.String(500), nullable=False, server_default=""),
            sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
            sa.Column("handled_by", sa.Integer(), nullable=True),
            sa.Column("handled_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("handle_reason", sa.String(300), nullable=False, server_default=""),
            sa.Column("handle_action", sa.String(16), nullable=False, server_default=""),
            sa.Column("blocked", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        )
        for col in ("item_id", "user_id", "status", "created_at"):
            op.create_index(f"ix_takedown_requests_{col}", "takedown_requests", [col])


def downgrade() -> None:
    op.drop_table("takedown_requests")
    op.drop_table("block_entries")
    with op.batch_alter_table("items") as b:
        b.drop_column("pin_ends_at")
        b.drop_column("pin_starts_at")
