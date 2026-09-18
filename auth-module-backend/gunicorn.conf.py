"""
Gunicorn 生产配置（Docker 部署使用）

启动命令：gunicorn --config gunicorn.conf.py "app:create_app()"

要点：
- 使用 gthread worker：SSE（/api/v1/sse/tasks/<id>）为长连接，每条连接占用一个线程，
  因此并发 SSE 数 ≈ workers × threads，可通过 GUNICORN_THREADS 调整。
- preload_app=True：应用工厂只在 master 进程中执行一次，
  避免多 worker 并发执行数据库迁移 / 种子数据造成重复写入。
- timeout 放大到 600s：生图、文档解析等异步链路存在长耗时请求。
"""
import os

bind = os.environ.get('GUNICORN_BIND', '0.0.0.0:5001')

# 进程与线程：gthread 模型，兼顾长连接（SSE）与并发
workers = int(os.environ.get('GUNICORN_WORKERS', '2'))
threads = int(os.environ.get('GUNICORN_THREADS', '8'))
worker_class = 'gthread'

# 心跳文件放入内存盘，避免磁盘 IO 阻塞导致的 worker 误判超时
worker_tmp_dir = '/dev/shm'

# 超时：单请求最长 600s（与前端 300s 超时 + 生图链路留出余量）
timeout = int(os.environ.get('GUNICORN_TIMEOUT', '600'))
graceful_timeout = 60
keepalive = 5

# 应用工厂只执行一次（迁移/种子数据仅跑一次）
preload_app = True

# 日志输出到容器标准输出，由 Docker 统一收集
accesslog = '-'
errorlog = '-'
loglevel = os.environ.get('GUNICORN_LOG_LEVEL', 'info')
access_log_format = '%({x-forwarded-for}i)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)sus'

# 信任 nginx 反向代理传入的转发头（配合 TRUST_PROXY_HEADERS=true 还原真实客户端 IP）
forwarded_allow_ips = '*'
