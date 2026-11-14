# ---------- 1. 构建前端 ----------
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm config set registry https://registry.npmmirror.com && npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------- 2. 后端运行镜像（同时托管前端静态文件）----------
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=Asia/Shanghai
WORKDIR /app/backend

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt

COPY backend/ ./
COPY --from=web /web/dist /app/frontend/dist

# 数据（封面、上传截图）放在卷里
RUN mkdir -p /app/backend/data/media
VOLUME ["/app/backend/data"]

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"

# 定时采集在进程内运行，只能起 1 个 worker（多 worker 会重复采集）
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*"]
