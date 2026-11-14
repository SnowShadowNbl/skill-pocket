from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import DateTime, create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.types import TypeDecorator

from .config import settings

_is_sqlite = settings.database_url.startswith("sqlite")

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False, "timeout": 30} if _is_sqlite else {},
    pool_pre_ping=True,
)

if _is_sqlite:
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """统一按 UTC 存取；SQLite 不支持时区，读出时补回 UTC。"""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is not None:
            value = value.astimezone(timezone.utc)
            if dialect.name == "sqlite":
                value = value.replace(tzinfo=None)
        return value

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# v1.2 之前的轻量补列（Alembic 基线 0001 之前的库可能缺这两列）
_LEGACY_COLUMNS = {
    "items": {"review_note": "TEXT NOT NULL DEFAULT ''", "favorited_at": "TIMESTAMP WITH TIME ZONE"},
}

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def _alembic_config(conn):
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.attributes["connection"] = conn
    return cfg


def upgrade_db() -> None:
    """建库 / 升级到最新版本。
    - 空库：按模型直接建表，标记为最新版本
    - v1.2 的库（没有 alembic_version）：补齐旧列，标记为基线 0001，再升级
    - 其他：正常升级
    """
    from alembic import command

    insp = inspect(engine)
    with engine.begin() as conn:
        cfg = _alembic_config(conn)
        if not insp.has_table("items"):
            Base.metadata.create_all(conn)
            command.stamp(cfg, "head")
            return
        if not insp.has_table("alembic_version"):
            for table, cols in _LEGACY_COLUMNS.items():
                have = {c["name"] for c in insp.get_columns(table)}
                for name, ddl in cols.items():
                    if name not in have:
                        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
            command.stamp(cfg, "0001")
        command.upgrade(cfg, "head")
