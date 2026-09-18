# 快速部署指南

本文档面向首次部署 EcomAI_image_Studio 的用户，覆盖环境要求、依赖安装、配置说明、启动命令与验证方法。

提供两条路径：

- **路径 A：Docker Compose 一键部署**（推荐，适合快速体验与生产部署）
- **路径 B：本地开发部署**（适合二次开发与调试）

---

## 目录

- [1. 环境要求](#1-环境要求)
- [2. 路径 A：Docker Compose 一键部署](#2-路径-a-docker-compose-一键部署)
- [3. 路径 B：本地开发部署](#3-路径-b-本地开发部署)
- [4. 配置说明](#4-配置说明)
- [5. 启动验证](#5-启动验证)
- [6. 运行测试](#6-运行测试)
- [7. 常见问题](#7-常见问题)

---

## 1. 环境要求

### 1.1 硬件建议

| 项目 | 最低 | 推荐 |
| --- | --- | --- |
| CPU | 2 核 | 4 核及以上 |
| 内存 | 4 GB | 8 GB 及以上 |
| 磁盘 | 10 GB 可用 | 40 GB 及以上（生成图片会持续占用 `uploads` 卷） |

> 说明：本项目的计算压力主要来自外部 AI 服务调用，本机主要承担 HTTP 服务、任务调度与图片落盘，因此硬件门槛不高；但批量套图会并发落盘，磁盘空间需要预留。

### 1.2 软件版本

| 软件 | 版本要求 | 用途 | 是否必需 |
| --- | --- | --- | --- |
| Docker | 24.0+ | 容器运行时 | 路径 A 必需 |
| Docker Compose | v2.20+（`docker compose` 子命令） | 服务编排 | 路径 A 必需 |
| Python | 3.10+（Docker 镜像使用 3.11） | 后端运行时 | 路径 B 必需 |
| pip | 随 Python 附带 | Python 依赖管理 | 路径 B 必需 |
| MySQL | 8.0+ | 业务数据库 | 路径 B 必需 |
| Redis | 7.x | 异步任务队列与 SSE 事件通道 | 路径 B 必需 |
| Node.js | 20.x | 前端构建 | 路径 B 必需 |
| npm | 10.x | 前端依赖管理 | 路径 B 必需 |
| MySQL 客户端 | 任意 | 执行初始化 SQL | 路径 B 必需 |

### 1.3 外部服务依赖

项目需要三类外部 AI 服务，均采用 OpenAI 兼容协议，可替换为任意兼容服务商：

| 服务类型 | 用途 | 示例模型名 |
| --- | --- | --- |
| 文本 LLM | 文案生成、提示词方案、Agent 规划 | `qwen3.6-plus-2026-04-02` |
| 多模态模型 | 商品图理解、AI 帮写、视觉合规审查、反推提示词 | `qwen3.5-omni-plus` |
| 图像生成/编辑模型 | 商品图生成、图片编辑、工具箱生图 | `gpt-image-2` |

> 可选：**生图计划分析**功能支持上传 PDF/Word/PPT/Excel 文档，需额外配置 MinerU 的 Token（`MINERU_TOKEN`）；不配置时该功能仅支持纯文本文件（txt / md / json）。

---

## 2. 路径 A：Docker Compose 一键部署

### 2.1 服务拓扑

`docker-compose.yml` 会启动 5 个服务：

| 服务 | 镜像 | 端口映射 | 说明 |
| --- | --- | --- | --- |
| `frontend` | 本地构建（nginx:1.27-alpine） | `${FRONTEND_PORT:-8080}` → 80 | 托管前端静态资源并反代 `/api` |
| `backend` | 本地构建（python:3.11-slim） | 仅容器内 5001 | Flask API（gunicorn gthread） |
| `worker` | 与 backend 同镜像 | 无 | ARQ 异步任务执行器 |
| `mysql` | mysql:8.0 | `127.0.0.1:${MYSQL_HOST_PORT:-3307}` → 3306 | 业务数据库 |
| `redis` | redis:7-alpine | `127.0.0.1:${REDIS_HOST_PORT:-6380}` → 6379 | 任务队列与事件通道 |

MySQL 与 Redis 仅绑定宿主机回环地址，不对外暴露。

### 2.2 部署步骤

```bash
# 1. 克隆仓库
git clone <your-repo-url> EcomAI_image_Studio
cd EcomAI_image_Studio

# 2. 生成环境变量文件
cp .env.docker.example .env

# 3. 编辑 .env，至少替换以下必填项（详见第 4 节）
#    MYSQL_ROOT_PASSWORD / SECRET_KEY / JWT_SECRET_KEY
#    INVITE_CODE_ENCRYPTION_KEY / USER_AI_KEY_ENCRYPTION_KEY
#    LLM_API_KEY / MULTIMODAL_API_KEY / IMAGE_GEN_API_KEY
#    以及对应的 *_API_BASE 与 *_MODEL_NAME
vi .env

# 4. 构建并启动
docker compose up -d --build

# 5. 观察启动过程（backend 首次启动会自动执行迁移与种子数据）
docker compose logs -f backend
```

### 2.3 启动顺序说明

Compose 通过健康检查控制启动顺序：

```
mysql (healthy) ─┐
                 ├─▶ backend (healthy) ─▶ frontend
redis (healthy) ─┘        ▲
                          │ 同镜像
                       worker
```

- `mysql` 与 `redis` 均通过健康检查后，`backend` 与 `worker` 才会启动。
- `backend` 首次启动时，MySQL 会自动执行挂载进 `/docker-entrypoint-initdb.d/` 的 `init_db.sql`（**仅在数据卷为空时执行**）；随后 backend 自身执行 `migrations/` 下的增量迁移与种子数据。
- `frontend` 等待 `backend` 健康后才启动。

### 2.4 常用运维命令

```bash
docker compose ps                      # 查看服务状态
docker compose logs -f backend worker  # 跟踪后端与 Worker 日志
docker compose restart backend worker  # 重启后端与 Worker（代码未变时）
docker compose up -d --build backend worker   # 代码变更后重建
docker compose down                    # 停止并移除容器（保留数据卷）
docker compose down -v                 # 停止并删除数据卷（清空数据库与上传文件，谨慎使用）
```

---

## 3. 路径 B：本地开发部署

### 3.1 准备 MySQL 与 Redis

**MySQL**

```bash
# 使用 root 登录并执行初始化脚本（会创建数据库 ecomai_auth 及全部表与种子数据）
cd auth-module-backend
mysql -u root -p < init_db.sql
```

验证：

```bash
mysql -u root -p -e "USE ecomai_auth; SHOW TABLES;"
```

**Redis**

```bash
# Docker 方式（最简）
docker run -d --name ecomai-redis -p 6379:6379 redis:7-alpine
```

### 3.2 启动后端 API

```bash
cd auth-module-backend

# 1. 安装依赖（建议先创建虚拟环境）
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt

# 2. 生成环境变量文件并填写
cp .env.example .env
#    至少填写 MYSQL_*、LLM_*、MULTIMODAL_*、IMAGE_GEN_* 各项

# 3. 启动 API（默认 http://localhost:5001）
python app.py
```

### 3.3 启动异步 Worker

**必须另开一个终端**，否则生图、批量套图、工具箱、编辑器等异步功能会一直停留在排队状态。

```bash
cd auth-module-backend
python worker.py
```

### 3.4 启动前端

```bash
cd ecom-ai-studio

npm ci          # 严格按 package-lock.json 安装
npm run dev     # http://localhost:5173
```

Vite 已配置开发代理：前端 `/api/*` 请求会转发到 `http://localhost:5001`，超时 600 秒（适配长耗时接口）。

### 3.5 前端生产构建

```bash
cd ecom-ai-studio
npm run build     # 类型检查 + 构建，产物在 dist/
npm run preview   # 本地预览构建产物
```

---

## 4. 配置说明

### 4.1 配置加载机制

后端配置集中在 [config.py](file:///d:/desktop/all_images/auth-module-backend/config.py)，分两个类：

- `Config`：Flask、MySQL、JWT、邮件、限流、验证码、邀请码、加密密钥等。
- `AIConfig`：LLM、多模态、图像生成、MinerU、缓存与上传限制。

加载顺序：`.env` 文件 → 环境变量 → 代码内默认值。环境变量优先级最高，**生产环境必须通过环境变量覆盖全部密钥**。

配置环境由 `FLASK_ENV` 决定，可选 `development` / `production` / `testing` / `default`（默认走 `development`）。

### 4.2 环境变量清单（Docker 部署）

对应模板文件：[.env.docker.example](file:///d:/desktop/all_images/.env.docker.example)

**镜像与端口**

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `IMAGE_TAG` | `latest` | 镜像标签，发版时递增便于回滚 |
| `FRONTEND_PORT` | `8080` | 前端对外访问端口 |
| `MYSQL_HOST_PORT` | `3307` | MySQL 映射到宿主机的端口（仅回环） |
| `REDIS_HOST_PORT` | `6380` | Redis 映射到宿主机的端口（仅回环） |

**数据库与队列**

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `MYSQL_ROOT_PASSWORD` | 无（必填） | MySQL root 密码 |
| `MYSQL_DATABASE` | `ecomai_auth` | 业务数据库名 |
| `TASK_RESULT_TTL` | `86400` | 任务状态在 Redis 中的保留秒数 |

> 容器内 `MYSQL_HOST` / `MYSQL_PORT` / `REDIS_URL` 已由 `docker-compose.yml` 固定为服务名（`mysql` / `redis`），无需在 `.env` 中配置。

**Flask 与安全**

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `FLASK_ENV` | `production` | 生产环境保持 `production`（关闭 debug） |
| `SECRET_KEY` | 无（必填） | Flask 会话密钥 |
| `JWT_SECRET_KEY` | 无（必填） | JWT 签名密钥 |
| `INVITE_CODE_ENCRYPTION_KEY` | 无（必填） | 团队邀请码 AES 加密密钥 |
| `USER_AI_KEY_ENCRYPTION_KEY` | 无（必填） | 用户自备 API Key 的 AES 加密密钥，**必须与邀请码密钥不同** |
| `CORS_ALLOWED_ORIGINS` | `*` | 允许的跨域来源，逗号分隔；同域部署保持默认即可 |
| `RATE_LIMIT_PER_MINUTE` | `200` | 每 IP 每分钟请求上限 |
| `TRUST_PROXY_HEADERS` | `true` | 位于 Nginx 之后时必须为 `true`，否则限流会退化为全局共享配额 |

**Gunicorn**

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `GUNICORN_WORKERS` | `2` | 工作进程数 |
| `GUNICORN_THREADS` | `8` | 每进程线程数；并发 SSE 连接数 ≈ workers × threads |
| `GUNICORN_TIMEOUT` | `600` | 单请求超时（秒） |
| `GUNICORN_LOG_LEVEL` | `info` | 日志级别 |
| `GUNICORN_BIND` | `0.0.0.0:5001` | 监听地址（一般无需修改） |

**AI 服务**

| 变量 | 说明 |
| --- | --- |
| `LLM_MODEL_NAME` / `LLM_API_BASE` / `LLM_API_KEY` | 文本模型名称 / 兼容接口地址 / 密钥 |
| `MULTIMODAL_MODEL_NAME` / `MULTIMODAL_API_BASE` / `MULTIMODAL_API_KEY` | 多模态模型名称 / 地址 / 密钥 |
| `IMAGE_GEN_MODEL_NAME` / `IMAGE_GEN_API_BASE` / `IMAGE_GEN_API_KEY` | 图像生成模型名称 / 地址 / 密钥 |
| `IMAGE_GEN_MAX_RETRIES` | 生图失败重试次数，默认 `2` |
| `IMAGE_GEN_TIMEOUT` | 生图/编辑请求超时秒数，默认 `300` |
| `MINERU_TOKEN` | MinerU 文档解析 Token（可选） |
| `COMPLIANCE_REVIEW_ENABLED` | 批量链路生成后是否自动执行视觉合规审查，默认 `true` |

**可调优参数（可选）**

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `LLM_MAX_RETRIES` | `2` | LLM 调用重试次数 |
| `MULTIMODAL_TIMEOUT` | `300` | 多模态单次请求超时（秒） |
| `MULTIMODAL_MAX_RETRIES` | `2` | 多模态调用重试次数 |
| `ANALYSIS_CACHE_TTL` | `3600` | 生图计划分析结果缓存秒数 |
| `FILE_UPLOAD_MAX_SIZE` | `52428800` | 单文件上传上限（字节，默认 50 MB） |
| `CHUNK_SIZE` | `5242880` | 分块上传分片大小（字节，默认 5 MB） |
| `SITE_DICT_PATH` | `config/dictionaries` | 站点/场景字典目录 |

### 4.3 环境变量清单（本地开发）

对应模板文件：[auth-module-backend/.env.example](file:///d:/desktop/all_images/auth-module-backend/.env.example)

本地开发除上表中的 AI 与 Flask 配置外，还需要数据库直连参数：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `MYSQL_HOST` | `localhost` | 数据库地址 |
| `MYSQL_PORT` | `3306` | 数据库端口 |
| `MYSQL_USER` | `root` | 数据库用户 |
| `MYSQL_PASSWORD` | 无（必填） | 数据库密码 |
| `MYSQL_DATABASE` | `ecomai_auth` | 数据库名 |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis 连接串 |

### 4.4 邮件服务配置（可选）

验证码发送依赖 SMTP。相关配置项位于 `Config` 类：

| 配置项 | 说明 |
| --- | --- |
| `SMTP_SERVER` | SMTP 服务器地址 |
| `SMTP_PORT` | SMTP 端口 |
| `SMTP_USE_SSL` | 是否使用 SSL |
| `SMTP_USERNAME` | 发件邮箱（通过环境变量 `SMTP_USERNAME` 注入） |
| `SMTP_PASSWORD` | 邮箱授权码（通过环境变量 `SMTP_PASSWORD` 注入） |
| `SMTP_FROM_NAME` | 发件人显示名称 |

> 未配置 SMTP 时，注册/验证码登录会失败，但密码登录不受影响。

---

## 5. 启动验证

### 5.1 服务健康检查

```bash
# Docker 部署
curl http://localhost:8080/healthz            # 期望输出 ok
curl http://localhost:8080/api/v1/health      # 期望 {"code":0,...,"status":"healthy"}

# 本地开发
curl http://localhost:5001/api/v1/health
curl http://localhost:5001/
```

### 5.2 数据库校验

```bash
mysql -u root -p -e "USE ecomai_auth; SELECT COUNT(*) AS tables_count FROM information_schema.tables WHERE table_schema='ecomai_auth';"
```

期望 `tables_count` 为 25 左右（业务表 + `_migrations`），并且以下关键表存在：

```bash
mysql -u root -p -e "USE ecomai_auth; SHOW TABLES LIKE '%batch%'; SHOW TABLES LIKE 'feature_pricing';"
```

### 5.3 Redis 与 Worker 校验

```bash
# Redis 连通性
docker compose exec redis redis-cli ping        # 期望 PONG
redis-cli -p 6379 ping                          # 本地开发

# Worker 是否注册了任务（查看启动日志）
docker compose logs worker | grep -i "worker"
```

### 5.4 端到端功能验证

按以下顺序验证，可覆盖主要链路：

1. **注册/登录**：打开前端首页 → 注册新账号，或使用初始化脚本内置的开发测试账号登录（账号信息与上线前处理方式见 [SECURITY.md](SECURITY.md#4-开发测试默认凭据)）。
2. **余额检查**：进入「充值中心」，确认套餐列表能正常加载（验证 `pricing_plans` 表与公开接口）。
3. **文生图（最快的生图验证）**：进入「AI 工具箱 → 文生图」，输入提示词生成一张图片。该接口为同步链路，可快速验证 AI 生图通道是否配置正确。
4. **简单模式商品图**：进入「AI 商品图」，上传商品图 → 选择站点与场景 → 生成，观察进度条是否通过 SSE 实时更新（验证 Redis + ARQ + SSE 全链路）。
5. **批量套图**：在商品图页底部打开批量面板 → 选择多个站点与图型 → 提交，观察批次进度与逐项结果。
6. **AI 图片编辑器**：从任意生成结果的卡片进入编辑器，试用「裁剪」「AI 抠图」以及 AI 助手的自然语言指令。

> 若第 3 步即失败，问题通常在 AI 服务配置（`IMAGE_GEN_*`）；若第 4 步一直停在排队，问题通常在 Worker 或 Redis。

---

## 6. 运行测试

### 6.1 后端测试

测试使用独立的 `ecomai_auth_test` 数据库（见 `TestingConfig`）。

```bash
cd auth-module-backend

# 1. 创建并初始化测试库
mysql -u root -p -e "CREATE DATABASE IF NOT EXISTS ecomai_auth_test CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
# 将 init_db.sql 中的数据库名替换为测试库后导入
mysql -u root -p ecomai_auth_test < init_db.sql

# 2. 运行测试
python -m pytest tests/ -v
```

部分测试依赖 Redis，请确保 Redis 已启动。

### 6.2 前端测试

```bash
cd ecom-ai-studio
npm test            # 单次运行
npm run test:watch  # 监听模式
```

前端测试基于 Vitest + happy-dom，覆盖工作台配置面板、合规阻断、批量面板与纯函数工具。

---

## 7. 常见问题

### Q1：前端能打开，但所有接口返回「无法连接到服务器」

后端未启动，或前端代理地址不对。检查：

```bash
curl http://localhost:5001/api/v1/health
```

若后端正常，确认 `vite.config.ts` 中的代理目标与实际后端端口一致（默认 `http://localhost:5001`）。

### Q2：提交生成后进度一直停在「排队中」

异步 Worker 未启动。本地开发需要**两个终端**分别运行 `python app.py` 与 `python worker.py`；Docker 部署检查 `docker compose ps` 中 `worker` 是否处于 `running`。

### Q3：SSE 进度不更新，但最终结果能出来

反向代理缓冲了 SSE 流。确认 Nginx 对 `/api/v1/sse/` 关闭了缓冲（本项目 `nginx.conf` 已配置 `proxy_buffering off`）。若使用其他网关（如 CDN、云负载均衡），需同步关闭对应缓冲并放长读超时。

### Q4：数据库初始化脚本执行后表不完整

`init_db.sql` 只包含基础表；其余表由后端启动时通过 `migrations/` 自动补齐。请确保后端至少成功启动过一次，并检查启动日志中的 `[Migration]` 行。

### Q5：图片生成成功但前端显示不出来

检查 `uploads` 卷是否正确挂载与共享。`backend` 与 `worker` **必须挂载同一个 `backend_uploads` 卷**，否则 Worker 生成的图片文件 API 进程读不到。

### Q6：验证码收不到

SMTP 未配置或授权码无效。检查 `SMTP_USERNAME` / `SMTP_PASSWORD` 环境变量，并确认使用的是邮箱的「授权码」而非登录密码。

### Q7：Docker 部署后修改了代码，界面没变化

需要重新构建镜像：

```bash
docker compose up -d --build backend worker frontend
```

### Q8：Redis 重启后任务全部丢失

本项目 Redis 配置为 `appendonly yes` + `maxmemory-policy noeviction`，正常情况下重启不会丢数据。若使用外部 Redis，请确认未开启内存淘汰策略（淘汰会导致任务状态丢失）。
