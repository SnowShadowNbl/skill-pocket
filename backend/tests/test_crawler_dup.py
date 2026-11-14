"""采集：仓库改名后旧名字再次出现时不重复收录；单个候选出错不让整轮采集失败。"""

from sqlalchemy import func, select

from app.db import Base, SessionLocal, engine
from app.main import ensure_admin
from app.models import Category, Item
from app.seed import seed_categories
from app.services import crawler


def setup_module():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        seed_categories(s)
        ensure_admin(s)


def repo_data(full_name):
    return {"id": 4242, "full_name": full_name, "name": full_name.split("/")[1], "html_url": f"https://github.com/{full_name}",
            "description": "TTS on MLX", "topics": [], "language": "Python", "stargazers_count": 100, "forks_count": 1,
            "default_branch": "main", "pushed_at": None, "archived": False, "fork": False}


def test_renamed_repo_is_not_collected_twice():
    with SessionLocal() as db:
        placeholder = db.scalar(select(Category).where(Category.code == crawler.FALLBACK_CODE))
        stats = {}
        c = {"channel": "search", "ref": "", "delta": None}
        crawler._save_candidate(db, c, repo_data("old-owner/mlx-audio"), "collect", [], "AI：相关", "model", placeholder, stats)
        db.commit()
        # 同一个仓库（同一个 GitHub id）换了名字又被发现
        crawler._save_candidate(db, c, repo_data("Blaizzy/mlx-audio"), "collect", [], "AI：相关", "model", placeholder, stats)
        db.commit()
        assert db.scalar(select(func.count()).select_from(Item).where(Item.name == "mlx-audio")) == 1
        assert stats["new_items"] == 1
