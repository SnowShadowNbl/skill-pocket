"""命令行工具。

    python -m app.cli set-password      交互输入密码，把哈希写入 .env
    python -m app.cli init-env          生成 .env（随机 SECRET_KEY）
    python -m app.cli copy-db <目标库URL> [--from <源库URL>]
                                        把当前数据库（默认 .env 里的）完整复制到目标库，用于 SQLite → PostgreSQL 迁移
    python -m app.cli open-admin-setup [小时]  打开超级管理员 Admin 的「免密码首次登录」窗口（默认 24 小时，设置密码后永久关闭）
    python -m app.cli check-liveness    失效巡检：检查收录条目的 GitHub 原地址，失效的逻辑下线（服务器每天 03:30 定时执行，顺带汇总行为数据）
"""

import getpass
import secrets
import sys

from .auth import hash_password
from .config import BASE_DIR

ENV_PATH = BASE_DIR / ".env"
EXAMPLE_PATH = BASE_DIR / ".env.example"


def _set_env(key: str, value: str) -> None:
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    out, found = [], False
    for line in lines:
        if line.split("=", 1)[0].strip() == key:
            out.append(f"{key}={value}")
            found = True
        else:
            out.append(line)
    if not found:
        out.append(f"{key}={value}")
    ENV_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")


def init_env() -> None:
    if not ENV_PATH.exists():
        ENV_PATH.write_text(EXAMPLE_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    _set_env("SECRET_KEY", secrets.token_urlsafe(32))
    print(f"已生成 {ENV_PATH}")


def set_password() -> None:
    pw = getpass.getpass("新管理员密码: ")
    if pw != getpass.getpass("再输入一次: "):
        sys.exit("两次输入不一致")
    # bcrypt 哈希含 $，.env 里用单引号包住避免被当成变量展开
    _set_env("ADMIN_PASSWORD_HASH", f"'{hash_password(pw)}'")
    print("已写入 ADMIN_PASSWORD_HASH，重启后端生效")


def copy_db() -> None:
    from sqlalchemy import create_engine, func, inspect, select, text

    from .config import settings
    from .db import Base
    from . import models  # noqa: F401  注册所有表

    args = sys.argv[2:]
    if not args:
        sys.exit(__doc__)
    target_url = args[0]
    source_url = args[args.index("--from") + 1] if "--from" in args else settings.database_url
    src = create_engine(source_url)
    dst = create_engine(target_url)

    Base.metadata.create_all(dst)
    with dst.connect() as c:
        for t in Base.metadata.sorted_tables:
            if c.execute(select(func.count()).select_from(t)).scalar():
                sys.exit(f"目标库的 {t.name} 表已有数据，为避免覆盖已停止。请用空库。")

    src_tables = set(inspect(src).get_table_names())
    if "items" in src_tables and "alembic_version" not in src_tables:
        sys.exit("源库还没升级到 v1.3：先用新版本启动一次后端（自动迁移），再复制。")
    with src.connect() as s, dst.begin() as d:
        for t in Base.metadata.sorted_tables:
            if t.name not in src_tables:
                continue
            src_cols = {c["name"] for c in inspect(src).get_columns(t.name)}
            cols = [c for c in t.columns if c.name in src_cols]
            order = list(t.primary_key.columns) or cols[:1]
            rows = [dict(r._mapping) for r in s.execute(select(*cols).order_by(*order))]
            for i in range(0, len(rows), 500):
                d.execute(t.insert(), rows[i:i + 500])
            print(f"{t.name:<16} {len(rows):>6} 行")
        if dst.dialect.name == "postgresql":
            # 复制时保留了原 id，要把自增序列推到最大值之后
            for t in Base.metadata.sorted_tables:
                if "id" in t.columns and t.columns["id"].autoincrement and len(t.primary_key.columns) == 1:
                    d.execute(text(f"SELECT setval(pg_get_serial_sequence('{t.name}', 'id'), "
                                   f"COALESCE((SELECT MAX(id) FROM {t.name}), 0) + 1, false)"))
    # 目标库按最新模型建表，直接标记为最新版本
    from alembic import command

    from .db import _alembic_config
    with dst.begin() as d:
        command.stamp(_alembic_config(d), "head")
    print("复制完成")


def check_liveness() -> None:
    import logging

    from .db import upgrade_db
    from .services import liveness
    from .models import LivenessRun
    from .db import SessionLocal

    logging.basicConfig(level=logging.INFO)
    upgrade_db()
    run_id = liveness.run("schedule")
    with SessionLocal() as db:
        r = db.get(LivenessRun, run_id)
        print(f"失效巡检完成：检查 {r.checked}，新下线 {r.went_offline}，恢复 {r.restored}，失败 {r.errors}")
    # 顺带做每日的行为数据汇总与过期清理
    from .services import visits
    print(f"行为汇总：{visits.rollup()} 行，清理过期事件 {visits.purge_old()} 条")
    # 记一次服务器状态和 DeepSeek 余额（资源监控里的增长趋势、日均花费）
    from .services import resources
    st = resources.server_status()
    resources.deepseek_balance(force=True)
    print(f"服务器：内存 {st['memory'].get('used_pct')}%，磁盘 {st['disk']['used_pct']}%")


def open_admin_setup() -> None:
    from .db import upgrade_db
    from .services import admin_setup

    upgrade_db()
    hours = float(sys.argv[2]) if len(sys.argv) > 2 else 24
    until = admin_setup.open_window(hours)
    print(f"已打开 Admin 首次登录窗口，截止 {until.astimezone().strftime('%Y-%m-%d %H:%M')}；设置密码后自动关闭")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    {"set-password": set_password, "init-env": init_env, "copy-db": copy_db, "check-liveness": check_liveness, "open-admin-setup": open_admin_setup}.get(cmd, lambda: print(__doc__))()
