from pydantic import BaseModel, Field

from .models import Category, Comment, Item, User
from .seed import KINDS


class LoginIn(BaseModel):
    password: str


class PreviewIn(BaseModel):
    url: str


class ImportPick(BaseModel):
    sub_path: str = ""
    kind: str = "repo"
    name: str = ""
    description: str = ""


class ImportIn(BaseModel):
    url: str
    picks: list[ImportPick]


class InstallStep(BaseModel):
    title: str
    command: str | None = None
    note: str | None = None


class ItemCreate(BaseModel):
    """手动新建（非 GitHub 资源，或想直接手填）。"""

    name: str = Field(min_length=1, max_length=200)
    category_id: int
    summary: str = ""
    description: str = ""
    install_steps: list[InstallStep] = []
    homepage_url: str = ""
    kind: str = ""


class ItemUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    category_id: int | None = None
    summary: str | None = None
    description: str | None = None
    install_steps: list[InstallStep] | None = None
    homepage_url: str | None = None
    status: str | None = None
    kind: str | None = None
    rank_blurb: str | None = None


class CommentIn(BaseModel):
    content: str = Field(min_length=1, max_length=5000)
    input_type: str = "text"
    rating: int | None = Field(None, ge=1, le=5)


class CategoryIn(BaseModel):
    parent_id: int | None = None
    code: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")
    name: str = Field(min_length=1, max_length=64)
    icon: str = ""
    sort: int = 0
    enabled: bool = True
    remark: str = ""


class CategoryUpdate(BaseModel):
    name: str | None = None
    icon: str | None = None
    sort: int | None = None
    enabled: bool | None = None
    remark: str | None = None


# ---- 序列化 ----

def category_brief(c: Category) -> dict:
    group = c.parent or c
    return {"id": c.id, "code": c.code, "name": c.name, "group_code": group.code, "group_name": group.name,
            "icon": group.icon}


from .services.anim import anim_url  # noqa: E402
from .services.thumbs import thumb_url  # noqa: E402


def _cover_url(item: Item) -> str | None:
    return f"/media/{item.cover_path}" if item.cover_path else None


def image_urls(item: Item) -> list[str]:
    """图片集（第一张是封面）；老数据没有图片集时用封面。"""
    paths = item.images or ([item.cover_path] if item.cover_path else [])
    return [f"/media/{p}" for p in paths]


def github_url(item: Item) -> str | None:
    if not item.repo:
        return None
    if item.sub_path:
        return f"{item.repo.html_url}/tree/{item.repo.default_branch}/{item.sub_path}"
    return item.repo.html_url


def kind_brief(kind: str) -> dict | None:
    if kind not in KINDS:
        return None
    label, icon, _ = KINDS[kind]
    return {"key": kind, "name": label, "icon": icon}


def ai_label(model: str) -> str | None:
    from .services.extract import model_label
    return model_label(model) if model else None


def public_user(u: User | None) -> dict | None:
    """别人能看到的用户信息：只有昵称和头像，不含邮箱。"""
    if u is None:
        return None
    if u.status == "deleted":
        return {"id": u.id, "nickname": "已注销用户", "avatar": ""}
    return {"id": u.id, "nickname": u.nickname or "用户", "avatar": u.avatar}


def _pinned_now(item) -> bool:
    from .services import pins

    return pins.state(item) == "active"


def item_card(item: Item, favs: set[int] | None = None) -> dict:
    return {
        "id": item.id,
        "name": item.name,
        "summary": item.summary,
        "stars": item.repo.stars if item.repo else None,
        "rating_avg": round(item.rating_avg, 1) if item.rating_avg else None,
        "rating_count": item.rating_count or 0,
        "cover_url": _cover_url(item),
        "cover_thumb_url": thumb_url(item.cover_path),  # v3.3.12 小程序用的位图缩略图
        "cover_source": item.cover_source,
        "pinned": _pinned_now(item),
        "category": category_brief(item.category),
        "source": item.source,
        "status": item.status,
        "ai_status": item.ai_status,
        "repo_full_name": item.repo.full_name if item.repo else None,
        "sub_path": item.sub_path,
        "collected_at": item.collected_at,
        "favorited": favs is not None and item.id in favs,
        "kind": kind_brief(item.kind),
        "uploader": public_user(item.creator) if item.source == "manual" else None,
        "offline": item.status == "offline",
        "offline_reason": item.offline_reason if item.status == "offline" else "",
        "review_state": item.review_state,
    }


def item_detail(item: Item, comment_count: int, rankings: list[dict], favs: set[int] | None = None,
                favorite: dict | None = None) -> dict:
    repo = item.repo
    return {
        **item_card(item, favs),
        "cover_anim_url": anim_url(item.cover_path),  # v3.3.13 小程序详情页的动图封面（只有 SVG 封面有）
        "favorite": favorite,
        "ai_model": ai_label(item.ai_model),
        "rank_blurb": item.rank_blurb,
        "rank_blurb_model": ai_label(item.rank_blurb_model),
        "description": item.description,
        "install_steps": item.install_steps or [],
        "homepage_url": item.homepage_url,
        "github_url": github_url(item),
        "clone_url": f"{repo.html_url}.git" if repo else None,
        "cover_source": item.cover_source,
        "images": image_urls(item),
        "ai_error": item.ai_error,
        "ai_confidence": item.ai_confidence,
        "locked_fields": item.locked_fields or [],
        "stars_at_collect": item.stars_at_collect,
        "updated_at": item.updated_at,
        "repo": {
            "full_name": repo.full_name, "html_url": repo.html_url, "language": repo.language,
            "license": repo.license, "forks": repo.forks, "topics": repo.topics or [],
            "pushed_at": repo.pushed_at, "archived": repo.archived, "last_synced_at": repo.last_synced_at,
        } if repo else None,
        "rankings": rankings,
        "comment_count": comment_count,
    }


def comment_out(c: Comment, me: User | None = None) -> dict:
    author = public_user(c.user) if c.user_id else {"id": None, "nickname": "历史用户", "avatar": ""}
    return {"id": c.id, "item_id": c.item_id, "content": c.content, "input_type": c.input_type,
            "created_at": c.created_at, "author": author, "status": c.status or "visible", "rating": c.rating,
            "can_delete": me is not None and (me.role in ("admin", "subadmin", "moderator") or c.user_id == me.id)}
