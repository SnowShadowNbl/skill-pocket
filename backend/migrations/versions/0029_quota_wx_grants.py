"""v3.3.91 免费额度按微信发放：quota_wx_grants 登记领过的 openid / unionid；回填已领过免费额度的微信账号

Revision ID: 0029
Revises: 0028
"""

import sqlalchemy as sa
from alembic import op

revision = "0029"
down_revision = "0028"


def upgrade() -> None:
    bind = op.get_bind()
    if "quota_wx_grants" not in sa.inspect(bind).get_table_names():
        op.create_table(
            "quota_wx_grants",
            sa.Column("wx_key", sa.String(64), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_quota_wx_grants_user_id", "quota_wx_grants", ["user_id"])
    # 已经领过免费额度的微信账号（含邮箱 + 微信）登记进去，之后同一个微信换账号不再重复发
    rows = bind.execute(sa.text("SELECT id, wx_openid, wx_unionid FROM users WHERE quota_balance IS NOT NULL AND wx_openid IS NOT NULL")).all()
    have = {r[0] for r in bind.execute(sa.text("SELECT wx_key FROM quota_wx_grants")).all()}
    for uid, openid, unionid in rows:
        for k in (openid, unionid):
            if k and k not in have:
                bind.execute(sa.text("INSERT INTO quota_wx_grants (wx_key, user_id, created_at) VALUES (:k, :u, CURRENT_TIMESTAMP)"),
                             {"k": k, "u": uid})
                have.add(k)


def downgrade() -> None:
    op.drop_index("ix_quota_wx_grants_user_id", "quota_wx_grants")
    op.drop_table("quota_wx_grants")
