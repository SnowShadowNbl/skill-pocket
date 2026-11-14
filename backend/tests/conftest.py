import os
import tempfile
from pathlib import Path

# 测试用临时数据库，必须在导入 app 之前设置
_tmp = Path(tempfile.mkdtemp()) / "test.db"
# 设置 TEST_DATABASE_URL 可让同一套测试跑在 PostgreSQL 上
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{_tmp.as_posix()}"
os.environ["CRAWL_ENABLED"] = "false"
os.environ["RANK_TOP_N"] = "3"
# 测试不调用真实的 AI / GitHub
os.environ["AI_API_KEY"] = ""
os.environ["AI_BASE_URL"] = ""
# 测试不发真实邮件；接口直接返回验证码；人机校验降低难度
os.environ["SES_SECRET_ID"] = ""
os.environ["SES_SECRET_KEY"] = ""
os.environ["AUTH_DEV_CODES"] = "true"
os.environ["POW_BITS"] = "6"
# 老测试不走二次验证；专门的测试里再打开
os.environ["ADMIN_VERIFY_REQUIRED"] = "false"


def solve_pow(ch: dict) -> str:
    import hashlib
    n = 0
    while True:
        d = hashlib.sha256(f"{ch['salt']}:{n}".encode()).digest()
        bits = 0
        for b in d:
            if b == 0:
                bits += 8
                continue
            bits += 8 - b.bit_length()
            break
        if bits >= ch["bits"]:
            return str(n)
        n += 1


def login_client(email: str = "u@example.com", role: str = "user"):
    """建（或复用）一个用户并返回已登录的 TestClient。"""
    from fastapi.testclient import TestClient
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.main import app
    from app.models import User

    c = TestClient(app)
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.email == email))
        if u is None:
            u = User(email=email, nickname=email.split("@")[0], role=role, status="active")
            db.add(u)
            db.commit()
        from starlette.requests import Request

        from app import auth
        token = auth.create_session(db, u, Request({"type": "http", "headers": [], "client": ("127.0.0.1", 0)}))
    c.headers["Authorization"] = f"Bearer {token}"
    return c

os.environ["EMBEDDING_API_KEY"] = ""
os.environ["GEO_DOWNLOAD"] = "false"
