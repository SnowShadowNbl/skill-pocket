from datetime import date, datetime

from sqlalchemy import false as sa_false
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, UTCDateTime, utcnow


class Category(Base):
    """分类字典，两级：大类(parent_id 为空) → 子类。条目只能挂子类。"""

    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(64))
    icon: Mapped[str] = mapped_column(String(16), default="")
    sort: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    remark: Mapped[str] = mapped_column(Text, default="")
    # v3.3.50 分类合并：被合并的分类停用，旧 code 的筛选改到这个分类
    merged_into_id: Mapped[int | None] = mapped_column(Integer)

    parent: Mapped["Category | None"] = relationship(remote_side="Category.id", back_populates="children")
    children: Mapped[list["Category"]] = relationship(back_populates="parent", order_by="Category.sort")


class Repo(Base):
    """GitHub 仓库。一个仓库可对应多个条目（monorepo 里的多个 Skill）。"""

    __tablename__ = "repos"

    id: Mapped[int] = mapped_column(primary_key=True)
    github_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    full_name: Mapped[str] = mapped_column(String(200), index=True)
    html_url: Mapped[str] = mapped_column(String(300))
    gh_description: Mapped[str] = mapped_column(Text, default="")
    topics: Mapped[list] = mapped_column(JSON, default=list)
    language: Mapped[str] = mapped_column(String(64), default="")
    license: Mapped[str] = mapped_column(String(64), default="")
    stars: Mapped[int] = mapped_column(Integer, default=0)
    forks: Mapped[int] = mapped_column(Integer, default=0)
    default_branch: Mapped[str] = mapped_column(String(100), default="main")
    pushed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    readme_sha: Mapped[str] = mapped_column(String(64), default="")
    # active / rejected（被删除后拉黑）/ ignored（判定为不相关）；后两者自动采集都跳过
    repo_status: Mapped[str] = mapped_column(String(16), default="active")
    # v3.3 版本更新提醒：最近一次看到的 Release 标签（空 = 还没检查过或没有 Release）
    latest_release: Mapped[str] = mapped_column(String(100), default="", server_default="")
    last_synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    items: Mapped[list["Item"]] = relationship(back_populates="repo")


class Item(Base):
    __tablename__ = "items"
    __table_args__ = (UniqueConstraint("repo_id", "sub_path"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    repo_id: Mapped[int | None] = mapped_column(ForeignKey("repos.id", ondelete="SET NULL"), index=True)
    sub_path: Mapped[str] = mapped_column(String(300), default="")
    name: Mapped[str] = mapped_column(String(200), index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), index=True)
    summary: Mapped[str] = mapped_column(String(500), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    # [{"title": str, "command": str|None, "note": str|None}]
    install_steps: Mapped[list] = mapped_column(JSON, default=list)
    homepage_url: Mapped[str] = mapped_column(String(500), default="")
    cover_path: Mapped[str] = mapped_column(String(300), default="")
    # 图片集（media 下的相对路径，按顺序展示；第一张同时是封面 cover_path）
    images: Mapped[list] = mapped_column(JSON, default=list)
    # readme / ai / upload / placeholder
    cover_source: Mapped[str] = mapped_column(String(16), default="placeholder")
    # v3.0.1 首页置顶：管理员给的权重，>0 时在「今日」排序里排在最前（权重大的更靠前）
    pin_weight: Mapped[int] = mapped_column(Integer, default=0, server_default="0", index=True)
    # v3.3.46 后台批次 3a：排除出榜单（疑似刷星等），不下线
    rank_excluded: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false(), index=True)
    rank_exclude_reason: Mapped[str] = mapped_column(String(300), default="", server_default="")
    rank_excluded_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    rank_excluded_by: Mapped[int | None] = mapped_column(Integer)
    # v3.3.48 推荐位排期：置顶的生效时间段（为空表示不限）；不在时间段内的置顶不参与首页排序
    pin_starts_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    pin_ends_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    # v3.3 好用度（口碑）：每位用户最近一次打分的平均值与人数，评论增删时重算
    rating_avg: Mapped[float | None] = mapped_column(Float)
    rating_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # auto / manual
    source: Mapped[str] = mapped_column(String(16), default="manual", index=True)
    # candidate / pending_review（采集待确认）/ awaiting（用户提交审核中）/ declined（审核未通过）
    # / published / hidden / offline（原地址失效，逻辑下线）/ rejected
    status: Mapped[str] = mapped_column(String(16), default="published", index=True)
    # pending / running / done(AI) / rule(规则兜底) / failed
    ai_status: Mapped[str] = mapped_column(String(16), default="pending")
    ai_error: Mapped[str] = mapped_column(Text, default="")
    ai_confidence: Mapped[float | None] = mapped_column(Float)
    # 待确认条目的判定理由（关键词 / AI 预判）
    review_note: Mapped[str] = mapped_column(Text, default="")
    # 被人工修改过的字段，重新提炼时跳过
    locked_fields: Mapped[list] = mapped_column(JSON, default=list)
    # v1.2 的全站收藏时间，v1.3 起改用 favorites 表；保留列只为迁移旧数据
    favorited_at: Mapped[datetime | None] = mapped_column(UTCDateTime, index=True)
    # 使用类型：agent_skill / model / app / dev / demo；空表示还没判定
    kind: Mapped[str] = mapped_column(String(16), default="", index=True)
    kind_confidence: Mapped[float | None] = mapped_column(Float)
    # 提炼时实际使用的模型（界面上的 AI 标签显示它）
    ai_model: Mapped[str] = mapped_column(String(100), default="")
    # 榜单中文详解：只给上榜条目生成；basis 存生成时依据的文档开头，用来判断 README 是否大改
    rank_blurb: Mapped[str] = mapped_column(Text, default="")
    rank_blurb_model: Mapped[str] = mapped_column(String(100), default="")
    rank_blurb_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    rank_blurb_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    rank_blurb_basis: Mapped[str] = mapped_column(Text, default="")
    stars_at_collect: Mapped[int | None] = mapped_column(Integer)
    # 手动新增的上传者；系统采集为空
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    # 用户提交的审核阶段：'' 无需审核或已结束 / ai（AI 审核中）/ admin（待管理员审核）
    review_state: Mapped[str] = mapped_column(String(16), default="", index=True)
    # AI 生成的搜索标签（中英文同义词、用途、场景）
    search_tags: Mapped[list] = mapped_column(JSON, default=list)
    # 失效巡检：status=offline 时记录下线时间与原因；checked_at 为最近一次检查
    offline_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    offline_reason: Mapped[str] = mapped_column(String(200), default="")
    checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    collected_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    repo: Mapped[Repo | None] = relationship(back_populates="items")
    category: Mapped[Category] = relationship()
    creator: Mapped["User | None"] = relationship()
    comments: Mapped[list["Comment"]] = relationship(
        back_populates="item", cascade="all, delete-orphan", passive_deletes=True
    )


class Comment(Base):
    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), index=True)
    # 为空的是 v2.0 之前的匿名评论（显示为「历史用户」）
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    content: Mapped[str] = mapped_column(Text)
    # voice / text（语音只存转写文字）
    input_type: Mapped[str] = mapped_column(String(8), default="text")
    # v3.3 内容审核：visible 公开 / pending 待管理员审核（只有作者和管理员看得到）
    status: Mapped[str] = mapped_column(String(12), default="visible", index=True)
    # v3.3 好用度 1~5（可空：只写日志不打分）
    rating: Mapped[int | None] = mapped_column(Integer)
    # 审核说明：AI 给出的理由，或「AI 不可用，命中敏感词」
    review_reason: Mapped[str] = mapped_column(String(200), default="")
    # v3.3.44 后台批次 2a：最近一次处置（通过 / 驳回 / 删除 / 恢复）的人、时间、原因；status 增加 rejected / deleted（软删，保留内容）
    handled_by: Mapped[int | None] = mapped_column(Integer)
    handled_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    handle_reason: Mapped[str] = mapped_column(String(300), default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    item: Mapped[Item] = relationship(back_populates="comments")
    user: Mapped["User | None"] = relationship()


# ---- P2 起使用：快照、榜单、发现来源、任务日志 ----

class StarSnapshot(Base):
    __tablename__ = "star_snapshots"

    repo_id: Mapped[int] = mapped_column(ForeignKey("repos.id", ondelete="CASCADE"), primary_key=True)
    snap_date: Mapped[date] = mapped_column(Date, primary_key=True)
    stars: Mapped[int] = mapped_column(Integer)


class Ranking(Base):
    __tablename__ = "rankings"
    __table_args__ = (UniqueConstraint("period", "period_date", "category_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    period: Mapped[str] = mapped_column(String(8))  # daily / weekly / monthly
    period_date: Mapped[date] = mapped_column(Date)
    # 按子类出榜（分类越细越好）
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))
    generated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    category: Mapped[Category] = relationship()


class RankingEntry(Base):
    __tablename__ = "ranking_entries"

    ranking_id: Mapped[int] = mapped_column(ForeignKey("rankings.id", ondelete="CASCADE"), primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), primary_key=True)
    rank: Mapped[int] = mapped_column(Integer)
    stars_delta: Mapped[int] = mapped_column(Integer)
    stars_end: Mapped[int] = mapped_column(Integer)


class Discovery(Base):
    __tablename__ = "discoveries"

    id: Mapped[int] = mapped_column(primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repos.id", ondelete="CASCADE"), index=True)
    # awesome / trending_daily / trending_weekly / search / manual
    channel: Mapped[str] = mapped_column(String(32))
    channel_ref: Mapped[str] = mapped_column(String(300), default="")
    trending_delta: Mapped[int | None] = mapped_column(Integer)
    discovered_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Upload(Base):
    __tablename__ = "uploads"

    id: Mapped[int] = mapped_column(primary_key=True)
    image_path: Mapped[str] = mapped_column(String(300))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    ai_result: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class UploadItem(Base):
    __tablename__ = "upload_items"

    upload_id: Mapped[int] = mapped_column(ForeignKey("uploads.id", ondelete="CASCADE"), primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), primary_key=True)


class JobRun(Base):
    __tablename__ = "job_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_name: Mapped[str] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    status: Mapped[str] = mapped_column(String(16), default="running")
    stats: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")


class AiCall(Base):
    __tablename__ = "ai_calls"

    id: Mapped[int] = mapped_column(primary_key=True)
    purpose: Mapped[str] = mapped_column(String(16))  # AI-1..AI-6
    model: Mapped[str] = mapped_column(String(100))
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str] = mapped_column(Text, default="")
    # v2.6：由哪个账号的操作触发（AI 对比、搜索添加、截图识别、新增条目的提炼）；系统任务为空
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


# ---- 批次任务与入库日志 ----

class Task(Base):
    """一个批次任务：导入一批、截图识别后加入、批量中文化、补封面、每晚采集的提炼阶段等。"""

    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))  # 与 IngestLog.trigger 相同的取值
    title: Mapped[str] = mapped_column(String(200))
    source: Mapped[str] = mapped_column(String(16))  # auto / manual
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    total: Mapped[int] = mapped_column(Integer, default=0)
    done: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    # running / ok（全部成功）/ partial（有失败或未完成）/ failed
    status: Mapped[str] = mapped_column(String(16), default="running", index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class TaskItem(Base):
    __tablename__ = "task_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[int | None] = mapped_column(ForeignKey("items.id", ondelete="SET NULL"))
    seq: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(200))
    # pending / running / ok / failed / deferred（额度用完留到明天）
    status: Mapped[str] = mapped_column(String(16), default="pending")
    stage: Mapped[str] = mapped_column(String(32), default="")
    message: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class IngestLog(Base):
    """入库日志：每个条目在每个环节的成功 / 警告 / 失败。"""

    __tablename__ = "ingest_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"), index=True)
    item_id: Mapped[int | None] = mapped_column(ForeignKey("items.id", ondelete="SET NULL"), index=True)
    item_name: Mapped[str] = mapped_column(String(200), default="")
    repo: Mapped[str] = mapped_column(String(200), default="")
    source: Mapped[str] = mapped_column(String(16), index=True)  # auto / manual
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    trigger: Mapped[str] = mapped_column(String(32), index=True)
    stage: Mapped[str] = mapped_column(String(32), index=True)
    level: Mapped[str] = mapped_column(String(16), index=True)  # info / success / warn / error
    message: Mapped[str] = mapped_column(Text, default="")
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)


class ChangelogEntry(Base):
    """更新日志：按版本分组，每条一个分类（新增功能 / 修改功能 / 修复 Bug）。"""

    __tablename__ = "changelog_entries"
    __table_args__ = (UniqueConstraint("version", "title"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[str] = mapped_column(String(32), index=True)
    released_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    category: Mapped[str] = mapped_column(String(16))  # feature / change / fix
    title: Mapped[str] = mapped_column(String(200))
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


# ---- v1.3：收藏分类、搜索添加 / 长文识别、缓存 ----

# v1.3 没有用户体系时全站共用 owner_id = 0；v2.0 起 owner_id 是用户 id（迁移时 0 归给 admin）
SITE_OWNER = 0


class FavDimension(Base):
    """收藏的自定义维度（如「我的分类」「工作项目」）。系统维度（大类 / 使用类型）不入库。"""

    __tablename__ = "fav_dimensions"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(Integer, default=SITE_OWNER, index=True)
    name: Mapped[str] = mapped_column(String(40))
    sort: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    folders: Mapped[list["FavFolder"]] = relationship(
        back_populates="dimension", order_by="FavFolder.sort", cascade="all, delete-orphan", passive_deletes=True)


class FavFolder(Base):
    __tablename__ = "fav_folders"
    __table_args__ = (UniqueConstraint("dimension_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    dimension_id: Mapped[int] = mapped_column(ForeignKey("fav_dimensions.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(40))
    emoji: Mapped[str] = mapped_column(String(16), default="")
    sort: Mapped[int] = mapped_column(Integer, default=0)
    last_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    # v3.3 公开分享：有值时 /s/<token> 可以只读查看这个分类里的收藏；停止分享清空
    share_token: Mapped[str | None] = mapped_column(String(24), unique=True, index=True)
    # v3.3.44 管理员关闭分享：链接保留但打不开，用户也不能再开启；解除后原链接恢复
    share_closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    share_closed_by: Mapped[int | None] = mapped_column(Integer)
    share_closed_reason: Mapped[str] = mapped_column(String(300), default="", server_default="")
    # 分享页被打开的次数（v3.3.44 起统计；之前分享的为空 = 未知）
    share_views: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    dimension: Mapped[FavDimension] = relationship(back_populates="folders")


class Favorite(Base):
    __tablename__ = "favorites"
    __table_args__ = (UniqueConstraint("owner_id", "item_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(Integer, default=SITE_OWNER, index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), index=True)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)


class FavoriteFolderLink(Base):
    __tablename__ = "favorite_folder_links"

    favorite_id: Mapped[int] = mapped_column(ForeignKey("favorites.id", ondelete="CASCADE"), primary_key=True)
    folder_id: Mapped[int] = mapped_column(ForeignKey("fav_folders.id", ondelete="CASCADE"), primary_key=True, index=True)


class FinderJob(Base):
    """新增 Skill 的「搜索添加」和「长文识别」：一次查找的输入、进度和结果列表。"""

    __tablename__ = "finder_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))  # search / text
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    query: Mapped[str] = mapped_column(Text, default="")  # 搜索词，或长文原文
    source_url: Mapped[str] = mapped_column(String(1000), default="")
    # running / done / failed / imported
    status: Mapped[str] = mapped_column(String(16), default="running")
    # {"stage", "message", "plan", "candidates": [...], "error"}
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)


class CacheEntry(Base):
    """通用缓存：GitHub 搜索结果、AI 生成的搜索关键词等。"""

    __tablename__ = "cache_entries"

    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)


class AppMeta(Base):
    """一次性数据迁移的标记等少量键值。"""

    __tablename__ = "app_meta"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


# ---- v2.0-α：用户体系 ----

class User(Base):
    """用户。普通用户用邮箱登录；唯一的超级管理员用户名 admin（没有邮箱也能用密码登录）。"""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str | None] = mapped_column(String(254), unique=True)
    username: Mapped[str | None] = mapped_column(String(40), unique=True)
    nickname: Mapped[str] = mapped_column(String(40), default="")
    avatar: Mapped[str] = mapped_column(String(40), default="")  # 预设头像的 key，空表示用昵称首字
    password_hash: Mapped[str] = mapped_column(String(100), default="")
    role: Mapped[str] = mapped_column(String(16), default="user")  # user / admin
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)  # active / disabled / deleted / merged
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    # v2.6：管理员给账号起的备注名（只在管理端显示）
    remark: Mapped[str] = mapped_column(String(60), default="")
    # v2.6：AI 额度余额（用户侧额度 = 真实 token × 2）。为空表示还没发放过免费额度，第一次用到时按默认值发放
    quota_balance: Mapped[int | None] = mapped_column(BigInteger)
    # v3.1 小程序：微信登录。合并掉的账号 status=merged、merged_into 指向保留下来的主账号
    wx_openid: Mapped[str | None] = mapped_column(String(64), unique=True)
    wx_unionid: Mapped[str | None] = mapped_column(String(64), index=True)
    merged_into: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    # v3.3.37 后台批次 0：注册渠道（web-pc / web-mobile / miniprogram，历史账号为空 = 未知）与最近一次登录的端和版本
    signup_channel: Mapped[str] = mapped_column(String(16), default="", server_default="")
    last_client: Mapped[str] = mapped_column(String(16), default="", server_default="")
    last_client_version: Mapped[str] = mapped_column(String(40), default="", server_default="")


class QuotaLedger(Base):
    """v2.6 额度变动记录：发放免费额度、充值、手动调整、重置。AI 消耗按天汇总在 QuotaDaily，不逐条记在这里。"""

    __tablename__ = "quota_ledger"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # grant / recharge / adjust / reset
    delta: Mapped[int] = mapped_column(BigInteger)  # 额度变化（可正可负）
    balance_after: Mapped[int] = mapped_column(BigInteger)
    amount_yuan: Mapped[float | None] = mapped_column(Float)  # 充值收到的钱（元），仅充值记录
    note: Mapped[str] = mapped_column(String(200), default="")
    operator_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)


class QuotaDaily(Base):
    """v2.6 每个账号每天的 AI 用量与当天结束时的剩余额度（北京时间的日期）。"""

    __tablename__ = "quota_daily"
    __table_args__ = (UniqueConstraint("user_id", "day", name="uq_quota_daily"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    calls: Mapped[int] = mapped_column(Integer, default=0)
    tokens: Mapped[int] = mapped_column(BigInteger, default=0)  # 真实 token
    used: Mapped[int] = mapped_column(BigInteger, default=0)  # 扣掉的额度（真实 token × 倍数）
    balance_end: Mapped[int] = mapped_column(BigInteger, default=0)  # 当天最后一次变动后的余额


class AuthSession(Base):
    """登录会话（一个设备一条）。只存令牌的哈希。"""

    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    device: Mapped[str] = mapped_column(String(120), default="")
    ip: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    # v3.3.37 登录时的端、版本和方式（email_code / password / wechat / wx_qr / merge）
    client: Mapped[str] = mapped_column(String(16), default="", server_default="")
    client_version: Mapped[str] = mapped_column(String(40), default="", server_default="")
    method: Mapped[str] = mapped_column(String(16), default="", server_default="")


class EmailCode(Base):
    __tablename__ = "email_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), index=True)
    purpose: Mapped[str] = mapped_column(String(16))  # login / reset / change / delete
    code_hash: Mapped[str] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    ip: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class EmailLog(Base):
    """每一封发出（或发送失败）的邮件，管理端可查。"""

    __tablename__ = "email_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), index=True)
    purpose: Mapped[str] = mapped_column(String(16))
    provider: Mapped[str] = mapped_column(String(16))  # ses / console
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)


# ---- v2.0：审核、操作日志、反馈、语义搜索、失效巡检 ----

class ItemReview(Base):
    """上线日志：用户提交条目的每一次审核结论（AI 或管理员），以及撤回下线。"""

    __tablename__ = "item_reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int | None] = mapped_column(ForeignKey("items.id", ondelete="SET NULL"), index=True)
    item_name: Mapped[str] = mapped_column(String(200), default="")
    submitter_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    reviewer: Mapped[str] = mapped_column(String(16))  # ai / admin
    reviewer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decision: Mapped[str] = mapped_column(String(16))  # approve / reject / unsure / revoke / restore
    confidence: Mapped[float | None] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(Text, default="")
    mode: Mapped[str] = mapped_column(String(16), default="")  # 当时的 AI 审核档位
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)


class ActivityLog(Base):
    """操作日志：用户和管理员的关键操作（保留 180 天）。"""

    __tablename__ = "activity_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    actor: Mapped[str] = mapped_column(String(16), default="user")  # user / admin / system / guest
    action: Mapped[str] = mapped_column(String(40), index=True)
    target_type: Mapped[str] = mapped_column(String(20), default="")
    target_id: Mapped[int | None] = mapped_column(Integer)
    summary: Mapped[str] = mapped_column(String(300), default="")
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    ip: Mapped[str] = mapped_column(String(64), default="")
    # v3.3.37 后台批次 0：管理操作留痕——原因、修改前后（只放变化的字段）、结果
    reason: Mapped[str] = mapped_column(String(300), default="", server_default="")
    before: Mapped[dict | None] = mapped_column(JSON)
    after: Mapped[dict | None] = mapped_column(JSON)
    result: Mapped[str] = mapped_column(String(16), default="ok", server_default="ok")  # ok / failed
    message: Mapped[str] = mapped_column(String(300), default="", server_default="")
    target_label: Mapped[str] = mapped_column(String(200), default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    contact_email: Mapped[str] = mapped_column(String(254), default="")
    # bug / feature / ux / content / account / other
    category: Mapped[str] = mapped_column(String(16), index=True)
    content: Mapped[str] = mapped_column(Text)
    input_type: Mapped[str] = mapped_column(String(8), default="text")
    images: Mapped[list] = mapped_column(JSON, default=list)
    diagnostics: Mapped[dict] = mapped_column(JSON, default=dict)
    item_id: Mapped[int | None] = mapped_column(ForeignKey("items.id", ondelete="SET NULL"))
    page_url: Mapped[str] = mapped_column(String(500), default="")
    # new / processing / resolved / wontfix
    status: Mapped[str] = mapped_column(String(16), default="new", index=True)
    priority: Mapped[str] = mapped_column(String(4), default="", index=True)  # P0~P4，非 Bug 为空
    # AI 分析：{suggested_category, priority, reason, cause, modules, impact, steps, similar_ids}
    ai_status: Mapped[str] = mapped_column(String(16), default="pending")  # pending / done / failed
    ai_analysis: Mapped[dict] = mapped_column(JSON, default=dict)
    admin_reply: Mapped[str] = mapped_column(Text, default="")
    replied_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    # v3.0.1 管理员的每一条回复：[{text, images: [media 路径], at, by}]；admin_reply 保留最后一条
    replies: Mapped[list | None] = mapped_column(JSON, default=list)
    user_unread: Mapped[bool] = mapped_column(Boolean, default=False)
    # v3.3.52 后台批次 4a 工单：负责人、首次响应 / 解决 / 关闭时间
    assignee_id: Mapped[int | None] = mapped_column(Integer, index=True)
    assigned_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    first_response_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class ItemEmbedding(Base):
    """条目向量（语义搜索）。basis_hash 是生成向量所依据文本的哈希，内容没变就不重算。"""

    __tablename__ = "item_embeddings"

    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), primary_key=True)
    model: Mapped[str] = mapped_column(String(64))
    dims: Mapped[int] = mapped_column(Integer)
    vector: Mapped[list] = mapped_column(JSON)
    basis_hash: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class LivenessRun(Base):
    """每晚失效巡检的报告。"""

    __tablename__ = "liveness_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    status: Mapped[str] = mapped_column(String(16), default="running")
    checked: Mapped[int] = mapped_column(Integer, default=0)
    went_offline: Mapped[int] = mapped_column(Integer, default=0)
    restored: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[int] = mapped_column(Integer, default=0)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


# ---- v2.1（P3）：游客识别与行为埋点 ----

class Visitor(Base):
    """一个浏览器一个游客编号（存在浏览器里，1 年有效）。登录后关联到用户，可追溯游客→注册的转化。"""

    __tablename__ = "visitors"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    first_seen: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    last_seen: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    first_ip: Mapped[str] = mapped_column(String(64), default="")
    last_ip: Mapped[str] = mapped_column(String(64), default="")
    first_geo: Mapped[str] = mapped_column(String(80), default="")
    last_geo: Mapped[str] = mapped_column(String(80), default="", index=True)
    device: Mapped[str] = mapped_column(String(60), default="")
    referrer: Mapped[str] = mapped_column(String(300), default="")
    landing: Mapped[str] = mapped_column(String(300), default="")
    visits: Mapped[int] = mapped_column(Integer, default=1)
    events: Mapped[int] = mapped_column(Integer, default=0)
    # 以游客身份来过、之后在这个浏览器上注册的时间（游客→注册转化）
    converted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class Event(Base):
    """行为事件明细（保留 180 天，每日汇总到 event_daily）。"""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    vid: Mapped[str] = mapped_column(String(40), index=True)
    user_id: Mapped[int | None] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(40), index=True)
    category: Mapped[str] = mapped_column(String(16), index=True)
    props: Mapped[dict] = mapped_column(JSON, default=dict)
    page: Mapped[str] = mapped_column(String(300), default="")
    ip: Mapped[str] = mapped_column(String(64), default="")
    geo: Mapped[str] = mapped_column(String(80), default="")
    client: Mapped[str] = mapped_column(String(16), default="", server_default="", index=True)  # v3.3.37 发生在哪一端
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)


class EventDaily(Base):
    """每日汇总（长期保留）：每个事件的次数与人数。"""

    __tablename__ = "event_daily"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    name: Mapped[str] = mapped_column(String(40), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)
    uv: Mapped[int] = mapped_column(Integer, default=0)


class CompareRun(Base):
    """v2.3 对比：用户勾选的 2~6 个条目（本站条目或外站 GitHub 仓库）与 AI 多维度对比结果。"""

    __tablename__ = "compare_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    # 条目集合的指纹（排序后的 key 列表做哈希），同一组 7 天内复用结果
    key: Mapped[str] = mapped_column(String(64), index=True)
    entries: Mapped[list] = mapped_column(JSON, default=list)  # [{"item_id": 1} | {"full_name": "a/b", "sub_path": ""}]
    subjects: Mapped[list] = mapped_column(JSON, default=list)  # 展示用的基本信息，分析前就能看到
    status: Mapped[str] = mapped_column(String(16), default="running")  # running / done / failed
    stage: Mapped[str] = mapped_column(String(200), default="")
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(String(300), default="")
    model: Mapped[str] = mapped_column(String(80), default="")
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class IpBan(Base):
    """禁止访问的 IP 或网段（CIDR）。命中后全站返回 403。"""

    __tablename__ = "ip_bans"

    id: Mapped[int] = mapped_column(primary_key=True)
    cidr: Mapped[str] = mapped_column(String(64), unique=True)  # 单个 IP 存成 /32 或 /128
    reason: Mapped[str] = mapped_column(String(200), default="")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class Notification(Base):
    """v3.3 站内消息：订阅分类上新、收藏的仓库发布新版本等。右上角铃铛查看。"""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # new_items / release / system / feedback_reply / admin_message
    title: Mapped[str] = mapped_column(String(200))
    # v3.3.57 管理员单发的消息：发送人
    sender_id: Mapped[int | None] = mapped_column(Integer, index=True)
    # v3.3.71 小范围公告：属于哪条公告（已读率按公告统计）
    announcement_id: Mapped[int | None] = mapped_column(Integer, index=True)
    body: Mapped[str] = mapped_column(String(500), default="")
    link: Mapped[str] = mapped_column(String(300), default="")
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)


class CategorySubscription(Base):
    """v3.3 订阅某个分类（大类或子类）的上新，每天汇总成一条站内消息。"""

    __tablename__ = "category_subscriptions"
    __table_args__ = (UniqueConstraint("user_id", "category_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"), index=True)
    last_notified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class WxQrLogin(Base):
    """v3.3.9 网页微信扫码：网页生成小程序码（scene = token），手机微信在小程序里确认。
    purpose=login：确认后网页轮询时签发该微信账号的网页令牌（令牌不落库，只发一次）；
    purpose=bind：网页已登录账号（web_user_id）绑定这个微信，必要时合并。"""

    __tablename__ = "wx_qr_logins"

    token: Mapped[str] = mapped_column(String(32), primary_key=True)
    purpose: Mapped[str] = mapped_column(String(8))  # login / bind
    status: Mapped[str] = mapped_column(String(12), default="pending")  # pending / scanned / confirmed / done / canceled
    web_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    wx_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)


class AdminView(Base):
    """v3.3.42 后台批次 1：管理员个人保存的筛选视图（query 是地址里的筛选字典，原样存取）。"""

    __tablename__ = "admin_views"
    __table_args__ = (UniqueConstraint("user_id", "scope", "name", name="uq_admin_view_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    scope: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(40))
    query: Mapped[dict] = mapped_column(JSON, default=dict)
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class ReasonTemplate(Base):
    """v3.3.44 驳回 / 处置理由模板：所有管理员可选用，超级管理员维护。"""

    __tablename__ = "reason_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    scope: Mapped[str] = mapped_column(String(32), index=True)  # item_reject / item_revoke / comment_reject / comment_delete / share_close
    text: Mapped[str] = mapped_column(String(300))
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class SearchTerm(Base):
    """v3.3.44 站内搜索词汇总：次数、无结果次数（服务端按实际结果统计），以及「大家在搜」屏蔽、已补收录标记。"""

    __tablename__ = "search_terms"

    id: Mapped[int] = mapped_column(primary_key=True)
    term: Mapped[str] = mapped_column(String(100), unique=True)  # 小写、去首尾空白
    shown: Mapped[str] = mapped_column(String(100), default="")  # 最近一次的原样写法
    searches: Mapped[int] = mapped_column(Integer, default=0)
    empty_count: Mapped[int] = mapped_column(Integer, default=0)
    last_results: Mapped[int | None] = mapped_column(Integer)
    last_at: Mapped[datetime | None] = mapped_column(UTCDateTime, index=True)
    blocked: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    block_reason: Mapped[str] = mapped_column(String(200), default="")
    blocked_by: Mapped[int | None] = mapped_column(Integer)
    blocked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    covered_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    covered_by: Mapped[int | None] = mapped_column(Integer)
    covered_note: Mapped[str] = mapped_column(String(200), default="")


class BlockEntry(Base):
    """v3.3.48 黑名单：仓库（owner/name）或 GitHub 账号（owner）。自动采集、用户提交、管理员导入都不再收录。"""

    __tablename__ = "block_entries"
    __table_args__ = (UniqueConstraint("kind", "value", name="uq_block_entry"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))  # repo / owner
    value: Mapped[str] = mapped_column(String(200))  # 小写
    reason: Mapped[str] = mapped_column(String(300), default="")
    source: Mapped[str] = mapped_column(String(16), default="manual")  # manual / takedown
    takedown_id: Mapped[int | None] = mapped_column(Integer)
    created_by: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class TakedownRequest(Base):
    """v3.3.48 下架申请：原作者（或维护者）在条目详情申请下架，管理员处理。"""

    __tablename__ = "takedown_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int | None] = mapped_column(ForeignKey("items.id", ondelete="SET NULL"), index=True)
    item_name: Mapped[str] = mapped_column(String(200), default="")
    repo_full_name: Mapped[str] = mapped_column(String(200), default="")
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    relation: Mapped[str] = mapped_column(String(16), default="author")  # author / maintainer / other
    reason: Mapped[str] = mapped_column(Text, default="")
    contact: Mapped[str] = mapped_column(String(200), default="")
    evidence_url: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)  # pending / approved / rejected
    handled_by: Mapped[int | None] = mapped_column(Integer)
    handled_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    handle_reason: Mapped[str] = mapped_column(String(300), default="")
    handle_action: Mapped[str] = mapped_column(String(16), default="")  # hide / delete
    blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)


class CategoryAudit(Base):
    """v3.3.50 AI 分类抽检：随机抽已上线条目让 AI 判断当前分类是否合适，管理员逐条确认保持或改分类。"""

    __tablename__ = "category_audits"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int | None] = mapped_column(Integer, index=True)
    item_id: Mapped[int | None] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), index=True)
    current_id: Mapped[int | None] = mapped_column(Integer)
    suggested_id: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[float | None] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(String(300), default="")
    agree: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)  # open / kept / moved
    decided_by: Mapped[int | None] = mapped_column(Integer)
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    decision_reason: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)


class FeedbackNote(Base):
    """v3.3.52 工单内部备注：只有管理员可见。"""

    __tablename__ = "feedback_notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    feedback_id: Mapped[int] = mapped_column(ForeignKey("feedback.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ReplyTemplate(Base):
    """v3.3.52 回复模板：工单回复 / 给用户发消息。支持 {nickname}、{id} 变量。"""

    __tablename__ = "reply_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    scope: Mapped[str] = mapped_column(String(32), index=True)  # feedback_reply / user_message
    title: Mapped[str] = mapped_column(String(40))
    text: Mapped[str] = mapped_column(String(500))
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Alert(Base):
    """v3.3.64 后台批次 6a：告警历史。同一 key 未恢复期间合并计数；条件消失后自动恢复（resolved_auto）。"""

    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(16), default="system", index=True)  # resource / backup / risk / system
    level: Mapped[str] = mapped_column(String(16), default="warn")  # info / warn / critical
    title: Mapped[str] = mapped_column(String(200))
    detail: Mapped[str] = mapped_column(Text, default="")
    count: Mapped[int] = mapped_column(Integer, default=1)
    first_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)  # open / acked / resolved
    acked_by: Mapped[int | None] = mapped_column(Integer)
    acked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    resolved_by: Mapped[int | None] = mapped_column(Integer)
    resolved_auto: Mapped[bool] = mapped_column(Boolean, default=False)
    notified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class ApiStat(Base):
    """v3.3.66 后台批次 6c：接口请求按小时汇总（不存逐条）。path 是路由模板（如 /api/items/{item_id}）。"""

    __tablename__ = "api_stats"
    __table_args__ = (UniqueConstraint("hour", "method", "path", name="uq_api_stat"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    hour: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    method: Mapped[str] = mapped_column(String(8))
    path: Mapped[str] = mapped_column(String(200))
    requests: Mapped[int] = mapped_column(Integer, default=0)
    errors_4xx: Mapped[int] = mapped_column(Integer, default=0)
    errors_5xx: Mapped[int] = mapped_column(Integer, default=0)
    total_ms: Mapped[int] = mapped_column(BigInteger, default=0)
    max_ms: Mapped[int] = mapped_column(Integer, default=0)
    buckets: Mapped[dict] = mapped_column(JSON, default=dict)  # 耗时分布：{"50": n, "100": n, ...}，用来估 p50 / p95
    last_error_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_status: Mapped[int | None] = mapped_column(Integer)


class ClientError(Base):
    """v3.3.66 客户端报错上报（网页 / 小程序）。同一指纹（端 + 版本 + 类型 + 页面 + 消息）合并计数。"""

    __tablename__ = "client_errors"

    id: Mapped[int] = mapped_column(primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True)
    client: Mapped[str] = mapped_column(String(16), default="", index=True)
    version: Mapped[str] = mapped_column(String(40), default="", index=True)
    kind: Mapped[str] = mapped_column(String(16), default="js_error")  # js_error / api_fail / miniapp_error
    page: Mapped[str] = mapped_column(String(300), default="")
    message: Mapped[str] = mapped_column(String(500), default="")
    stack: Mapped[str] = mapped_column(Text, default="")
    count: Mapped[int] = mapped_column(Integer, default=1)
    users: Mapped[int] = mapped_column(Integer, default=0)
    first_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    last_user_id: Mapped[int | None] = mapped_column(Integer, index=True)
    user_agent: Mapped[str] = mapped_column(String(300), default="")


class Tag(Base):
    """v3.3.71 用户标签（U04）：内测用户、贡献者、重点跟进等，只在后台可见，用来筛选和圈定公告对象。"""

    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(30), unique=True)
    color: Mapped[str] = mapped_column(String(16), default="blue")
    description: Mapped[str] = mapped_column(String(200), default="")
    created_by: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class UserTag(Base):
    __tablename__ = "user_tags"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True, index=True)
    created_by: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Announcement(Base):
    """v3.3.71 小范围公告：按标签 / 注册渠道 / 全部用户圈定对象，先预览再发送，以站内消息送达（kind=announcement）。"""

    __tablename__ = "announcements"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(40))
    text: Mapped[str] = mapped_column(String(500))
    link: Mapped[str] = mapped_column(String(300), default="")
    audience: Mapped[dict] = mapped_column(JSON, default=dict)  # {all: bool, tag_ids: [], channels: []}
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)  # draft / sent
    recipients: Mapped[int | None] = mapped_column(Integer)
    created_by: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    sent_by: Mapped[int | None] = mapped_column(Integer)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
