"""v1.3：使用类型、AI 模型、榜单详解、收藏分类、搜索添加 / 长文识别、缓存

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    with op.batch_alter_table("items") as b:
        b.add_column(sa.Column("kind", sa.String(16), nullable=False, server_default=""))
        b.add_column(sa.Column("kind_confidence", sa.Float(), nullable=True))
        b.add_column(sa.Column("ai_model", sa.String(100), nullable=False, server_default=""))
        b.add_column(sa.Column("rank_blurb", sa.Text(), nullable=False, server_default=""))
        b.add_column(sa.Column("rank_blurb_model", sa.String(100), nullable=False, server_default=""))
        b.add_column(sa.Column("rank_blurb_at", TS, nullable=True))
        b.add_column(sa.Column("rank_blurb_checked_at", TS, nullable=True))
        b.add_column(sa.Column("rank_blurb_basis", sa.Text(), nullable=False, server_default=""))
        b.create_index("ix_items_kind", ["kind"])

    op.create_table(
        "fav_dimensions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_id", sa.Integer(), nullable=False, index=True),
        sa.Column("name", sa.String(40), nullable=False),
        sa.Column("sort", sa.Integer(), nullable=False),
        sa.Column("created_at", TS, nullable=False),
    )
    op.create_table(
        "fav_folders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dimension_id", sa.Integer(), sa.ForeignKey("fav_dimensions.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String(40), nullable=False),
        sa.Column("emoji", sa.String(16), nullable=False),
        sa.Column("sort", sa.Integer(), nullable=False),
        sa.Column("last_used_at", TS, nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.UniqueConstraint("dimension_id", "name"),
    )
    op.create_table(
        "favorites",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_id", sa.Integer(), nullable=False, index=True),
        sa.Column("item_id", sa.Integer(), sa.ForeignKey("items.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_at", TS, nullable=False, index=True),
        sa.UniqueConstraint("owner_id", "item_id"),
    )
    op.create_table(
        "favorite_folder_links",
        sa.Column("favorite_id", sa.Integer(), sa.ForeignKey("favorites.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("folder_id", sa.Integer(), sa.ForeignKey("fav_folders.id", ondelete="CASCADE"), primary_key=True, index=True),
    )
    op.create_table(
        "finder_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("source_url", sa.String(1000), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_at", TS, nullable=False, index=True),
    )
    op.create_table(
        "cache_entries",
        sa.Column("key", sa.String(200), primary_key=True),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("expires_at", TS, nullable=False, index=True),
    )
    op.create_table(
        "app_meta",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
    )

    # v1.2 及之前的条目都由 deepseek-flash 提炼（界面 AI 标签显示它）
    op.execute("UPDATE items SET ai_model = 'deepseek-flash' WHERE ai_status = 'done'")

    # v1.2 的全站收藏迁移到 favorites（P1 全站共用 owner 0）
    op.execute(
        "INSERT INTO favorites (owner_id, item_id, note, created_at) "
        "SELECT 0, id, '', favorited_at FROM items WHERE favorited_at IS NOT NULL"
    )


def downgrade() -> None:
    for t in ("app_meta", "cache_entries", "finder_jobs", "favorite_folder_links", "favorites", "fav_folders", "fav_dimensions"):
        op.drop_table(t)
    with op.batch_alter_table("items") as b:
        b.drop_index("ix_items_kind")
        for c in ("rank_blurb_basis", "rank_blurb_checked_at", "rank_blurb_at", "rank_blurb_model", "rank_blurb",
                  "ai_model", "kind_confidence", "kind"):
            b.drop_column(c)
