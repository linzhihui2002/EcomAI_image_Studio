# syntax=docker/dockerfile:1

# ============================================================
# EcomAI Studio 后端镜像（Flask API + ARQ Worker 共用同一镜像）
# 构建上下文：auth-module-backend/
# ============================================================
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Shanghai

WORKDIR /app

# 系统依赖：curl 用于健康检查与容器内排障，tzdata 保证容器内时区正确
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl tzdata \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo "$TZ" > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

# 先装依赖再拷代码，利用 Docker 层缓存加速重复构建
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# 业务代码
COPY . .

# 非 root 用户运行；预建 uploads 目录（命名卷首次挂载会继承该目录的属主与权限）
RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /app/uploads/history_images/thumbs /app/uploads/chunks \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 5001

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -fsS http://127.0.0.1:5001/api/v1/health || exit 1

CMD ["gunicorn", "--config", "gunicorn.conf.py", "app:create_app()"]
