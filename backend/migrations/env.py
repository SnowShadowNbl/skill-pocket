"""Alembic 环境：由 app.db.upgrade_db() 以编程方式调用，连接从 config.attributes 传入。"""

from alembic import context

import app.models  # noqa: F401  注册全部表
from app.db import Base

connection = context.config.attributes["connection"]
context.configure(
    connection=connection,
    target_metadata=Base.metadata,
    render_as_batch=connection.dialect.name == "sqlite",
)
with context.begin_transaction():
    context.run_migrations()
