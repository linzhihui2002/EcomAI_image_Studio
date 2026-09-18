# 安全规范说明

本文档说明 EcomAI_image_Studio 对敏感信息的处理方式、环境变量的配置规范，以及代码发布到 GitHub 前的自查清单。

**核心原则：仓库中不出现任何真实密钥、密码或个人信息；所有敏感配置一律通过环境变量注入。**

---

## 目录

- [1. 敏感信息分类与处理方式](#1-敏感信息分类与处理方式)
- [2. 环境变量配置模板](#2-环境变量配置模板)
- [3. 仓库文件排除规则](#3-仓库文件排除规则)
- [4. 开发测试默认凭据](#4-开发测试默认凭据)
- [5. 代码层已实现的安全措施](#5-代码层已实现的安全措施)
- [6. 发布前自查清单](#6-发布前自查清单)
- [7. 密钥泄露应急处理](#7-密钥泄露应急处理)
- [8. 生产环境加固建议](#8-生产环境加固建议)

---

## 1. 敏感信息分类与处理方式

| 类别 | 具体项 | 处理方式 | 存放位置 |
| --- | --- | --- | --- |
| 数据库凭据 | `MYSQL_USER` / `MYSQL_PASSWORD` / `MYSQL_ROOT_PASSWORD` | 环境变量注入；仓库中只保留占位符 | `.env`（已 gitignore） |
| Flask 密钥 | `SECRET_KEY` | 环境变量注入；生产环境使用强随机值 | `.env` |
| JWT 密钥 | `JWT_SECRET_KEY` | 环境变量注入；生产环境使用强随机值 | `.env` |
| 邀请码加密密钥 | `INVITE_CODE_ENCRYPTION_KEY` | 环境变量注入；必须与用户 Key 密钥不同 | `.env` |
| 用户 API Key 加密密钥 | `USER_AI_KEY_ENCRYPTION_KEY` | 环境变量注入；必须与邀请码密钥不同 | `.env` |
| AI 服务密钥 | `LLM_API_KEY` / `MULTIMODAL_API_KEY` / `IMAGE_GEN_API_KEY` | 环境变量注入；仓库模板中为占位符 | `.env` |
| 邮件授权码 | `SMTP_USERNAME` / `SMTP_PASSWORD` | 环境变量注入；**不得硬编码在代码中** | `.env` |
| 文档解析 Token | `MINERU_TOKEN` | 环境变量注入 | `.env` |
| 用户自备模型 Key | 用户在平台填写 | AES-256-CBC 加密后存入 `user_ai_providers.api_key_cipher`；接口只返回掩码 | 数据库 |
| 用户密码 | 注册密码 | bcrypt 加盐哈希后存入 `users.password_hash`，不落明文 | 数据库 |
| 团队邀请码 | 团队邀请码 | SHA-256 哈希（查找）+ AES-256-CBC 加密（回显）双存储 | 数据库 |
| 开发测试账号 | 初始化脚本内置账号 | 仅限本地开发与自动化测试；**上线前必须修改或删除** | 数据库 |
| 运行产物 | 上传图片、任务日志、调研截图 | 通过 `.gitignore` 排除，不入库 | 本地磁盘 |

### 1.1 硬编码密钥的处理约定

以下位置**禁止**出现真实密钥：

- `config.py` 等配置文件中的默认值
- `.env.example` / `.env.docker.example` 等模板文件
- 测试代码中的断言数据
- README 与文档中的示例
- 前端源码（`VITE_*` 变量会打包进静态产物，**前端不得持有任何服务端密钥**）

`config.py` 中的配置项统一采用如下形式，仅在未配置时回退到开发用默认值：

```python
SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-only-change-me')
```

> 生产环境必须通过环境变量覆盖；`development` 默认值仅供本地调试。

### 1.2 前端环境变量

前端当前使用硬编码基址 `/api/v1`，通过 Nginx 反向代理访问后端，**不持有任何密钥**。

若后续需要引入构建期变量，请注意：**Vite 的 `VITE_*` 变量会被内联进前端产物，任何访问者都能读取**，因此只允许放置非敏感配置（如应用名称、展示用开关），严禁放置 API Key、数据库地址等。

---

## 2. 环境变量配置模板

### 2.1 Docker 部署模板

文件：[.env.docker.example](file:///d:/desktop/all_images/.env.docker.example)

```bash
cp .env.docker.example .env
```

模板内容（已全部使用占位符，可直接提交到仓库）：

```dotenv
# ---------- 镜像与端口 ----------
IMAGE_TAG=latest
FRONTEND_PORT=8080
MYSQL_HOST_PORT=3307
REDIS_HOST_PORT=6380

# ---------- MySQL ----------
MYSQL_ROOT_PASSWORD=change-me-strong-db-password
MYSQL_DATABASE=ecomai_auth

# ---------- Redis ----------
TASK_RESULT_TTL=86400

# ---------- Flask 基础配置 ----------
FLASK_ENV=production
SECRET_KEY=change-me-flask-secret
JWT_SECRET_KEY=change-me-jwt-secret

# 邀请码 / 用户自备模型 API Key 的 AES 加密密钥，二者必须不同
INVITE_CODE_ENCRYPTION_KEY=change-me-invite-aes-key
USER_AI_KEY_ENCRYPTION_KEY=change-me-user-ai-aes-key

CORS_ALLOWED_ORIGINS=*
RATE_LIMIT_PER_MINUTE=200
TRUST_PROXY_HEADERS=true

# ---------- Gunicorn ----------
GUNICORN_WORKERS=2
GUNICORN_THREADS=8
GUNICORN_TIMEOUT=600
GUNICORN_LOG_LEVEL=info

# ---------- AI 模型配置 ----------
LLM_MODEL_NAME=<your-llm-model>
LLM_API_BASE=<your-openai-compatible-base-url>
LLM_API_KEY=sk-replace-with-your-llm-api-key

MULTIMODAL_MODEL_NAME=<your-multimodal-model>
MULTIMODAL_API_BASE=<your-openai-compatible-base-url>
MULTIMODAL_API_KEY=sk-replace-with-your-multimodal-api-key

IMAGE_GEN_MODEL_NAME=<your-image-model>
IMAGE_GEN_API_BASE=<your-openai-compatible-base-url>
IMAGE_GEN_API_KEY=sk-replace-with-your-image-api-key
IMAGE_GEN_MAX_RETRIES=2
IMAGE_GEN_TIMEOUT=300

MINERU_TOKEN=
COMPLIANCE_REVIEW_ENABLED=true
```

### 2.2 本地开发模板

文件：[auth-module-backend/.env.example](file:///d:/desktop/all_images/auth-module-backend/.env.example)

```bash
cp auth-module-backend/.env.example auth-module-backend/.env
```

除上表内容外，额外需要：

```dotenv
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=change-me-db-password
MYSQL_DATABASE=ecomai_auth
REDIS_URL=redis://localhost:6379/0
```

### 2.3 生成强随机密钥

```bash
# Linux / macOS
python -c "import secrets; print(secrets.token_urlsafe(48))"

# Windows PowerShell
python -c "import secrets; print(secrets.token_urlsafe(48))"

# 或使用 OpenSSL
openssl rand -base64 48
```

四个密钥（`SECRET_KEY`、`JWT_SECRET_KEY`、`INVITE_CODE_ENCRYPTION_KEY`、`USER_AI_KEY_ENCRYPTION_KEY`）必须**互不相同**。

> 注意：`INVITE_CODE_ENCRYPTION_KEY` 与 `USER_AI_KEY_ENCRYPTION_KEY` 一经使用便不能随意更换——更换会导致已加密的邀请码与用户 API Key 无法解密。

### 2.4 密钥长度约束

`INVITE_CODE_ENCRYPTION_KEY` 与 `USER_AI_KEY_ENCRYPTION_KEY` 会被 SHA-256 派生出 32 字节 AES 密钥，因此任意长度的字符串都能工作，但建议不少于 32 个字符以保证强度。

---

## 3. 仓库文件排除规则

### 3.1 `.gitignore` 内容

文件：[.gitignore](file:///d:/desktop/all_images/.gitignore)

```gitignore
# 环境变量与密钥
.env
.env.*
!.env.example
!.env.docker.example

# Python
__pycache__/
*.pyc
*.pyo
.pytest_cache/
*.tsbuildinfo

# 依赖与构建产物
node_modules/
dist/
.vite/

# 运行时数据
auth-module-backend/uploads/
*.log
dump.rdb

# 编辑器与系统文件
.vscode/
.idea/
.DS_Store
Thumbs.db

# 测试与临时产物
after_pytest_task*.txt
baseline_pytest_task*.txt
auth-module-backend/tmp_e2e_*.py

# 本地调研与开发过程产物
prototype/
.trae/
```

### 3.2 排除规则说明

| 规则 | 排除内容 | 原因 |
| --- | --- | --- |
| `.env` / `.env.*` | 全部环境变量文件 | 含真实密钥；通过 `!` 反选保留模板文件 |
| `__pycache__/`、`*.pyc` | Python 字节码 | 编译产物，与源码无关 |
| `node_modules/`、`dist/`、`.vite/` | 前端依赖与构建产物 | 体积大且可重新生成 |
| `auth-module-backend/uploads/` | 用户上传与生成的图片 | 运行时数据，可能含用户素材 |
| `*.log`、`dump.rdb` | 日志与 Redis 快照 | 运行产物，可能含敏感请求内容 |
| `prototype/` | 本地调研脚本、E2E 截图、运行清单 | 开发过程产物，与项目功能无关 |
| `.trae/`、`.vscode/`、`.idea/` | IDE 配置 | 个人环境配置 |

### 3.3 Docker 构建上下文排除

`.dockerignore` 同样需要排除敏感文件：

- 后端 [auth-module-backend/.dockerignore](file:///d:/desktop/all_images/auth-module-backend/.dockerignore)
- 前端 [ecom-ai-studio/.dockerignore](file:///d:/desktop/all_images/ecom-ai-studio/.dockerignore)

前端 `.dockerignore` 已排除 `.env` / `.env.*`（保留 `.env.example`）、`node_modules`、`dist`、`.git` 等。

### 3.4 若敏感文件已被提交过

`.gitignore` **只对未跟踪文件生效**。如果敏感文件曾经被提交，需要先从 Git 历史中移除：

```bash
# 从索引中移除（保留本地文件）
git rm --cached auth-module-backend/.env

# 提交
git commit -m "chore: remove tracked env file"

# 若密钥已进入历史记录，必须做历史重写（谨慎操作，需团队协作）
# 推荐使用 git-filter-repo 或 BFG Repo-Cleaner
```

**关键提醒**：只要密钥进入过 Git 历史，就应视为**已泄露**，必须立即在服务商侧轮换（见第 7 节）。

---

## 4. 开发测试默认凭据

### 4.1 默认账号

`init_db.sql` 会写入两个**仅供本地开发与自动化测试**的账号：

| 角色 | 邮箱 | 用途 |
| --- | --- | --- |
| 管理员 | `admin@ecomai.local` | 本地验证管理后台功能 |
| 普通用户 | `user@ecomai.local` | 本地验证业务功能 |

密码为 bcrypt 哈希存储，明文不出现在 `init_db.sql` 中；测试用例所需的密码定义在 `auth-module-backend/tests/` 中。

> **风险提示**：这两个账号是公开可知的默认凭据。任何对外提供服务的部署都**必须**修改密码或直接删除。

### 4.2 上线前处理

```sql
-- 方式一：修改为强密码（密码哈希需用 bcrypt 生成）
-- python -c "import bcrypt; print(bcrypt.hashpw(b'<new-strong-password>', bcrypt.gensalt(12)).decode())"
UPDATE users
SET password_hash = '<生成的 bcrypt 哈希>'
WHERE email IN ('admin@ecomai.local', 'user@ecomai.local');

-- 方式二：直接删除默认账号（推荐对外部署时使用）
DELETE FROM users WHERE email IN ('admin@ecomai.local', 'user@ecomai.local');

-- 方式三：至少禁用账号
UPDATE users SET is_active = FALSE
WHERE email IN ('admin@ecomai.local', 'user@ecomai.local');
```

> 删除账号会级联删除其名下数据（历史记录、收藏、团队等），请在确认无有效业务数据后执行。

### 4.3 建议：改为环境变量驱动

若希望彻底摆脱固定默认凭据，可将 `init_db.sql` 中的 `users` 插入语句删除，改为在部署流程中通过脚本创建首个管理员：

```python
# 示例：用环境变量创建管理员
import os, bcrypt, pymysql

email = os.environ['ADMIN_EMAIL']
password = os.environ['ADMIN_PASSWORD']
password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt(12)).decode()

conn = pymysql.connect(
    host=os.environ['MYSQL_HOST'], port=int(os.environ.get('MYSQL_PORT', 3306)),
    user=os.environ['MYSQL_USER'], password=os.environ['MYSQL_PASSWORD'],
    database=os.environ['MYSQL_DATABASE'], charset='utf8mb4',
)
with conn.cursor() as cur:
    cur.execute(
        "INSERT INTO users (email, password_hash, role) VALUES (%s, %s, 'admin') "
        "ON DUPLICATE KEY UPDATE password_hash = VALUES(password_hash)",
        (email, password_hash),
    )
conn.commit()
conn.close()
```

### 4.4 其他默认值提醒

| 项目 | 默认值 | 处理建议 |
| --- | --- | --- |
| 示例兑换码 | `WELCOME2026` / `VIPGIFT50` / `BETA88` | 上线前删除或改码 |
| 示例团队与公告 | 5 个团队 + 3 条公告 | 上线前清理 |
| 示例 API 日志 | 79 条模拟数据 | 上线前清空 `api_request_logs` |
| 数据库端口 | `3307`（仅回环） | 保持不对外暴露 |
| Redis 端口 | `6380`（仅回环） | 保持不对外暴露 |

---

## 5. 代码层已实现的安全措施

### 5.1 认证与授权

| 措施 | 实现位置 |
| --- | --- |
| 密码 bcrypt 加盐哈希 | `utils/security.py` |
| JWT 无状态鉴权（HS256，24 小时有效期） | `utils/security.py`、`middleware/auth_middleware.py` |
| RBAC 角色校验装饰器 `@require_role` | `middleware/auth_middleware.py` |
| 令牌失效自动清理前端存储 | `src/api/client.ts` |

### 5.2 请求防护

| 措施 | 说明 |
| --- | --- |
| 参数化 SQL | 全部数据库查询使用参数化，防注入 |
| 全局限流 | `flask-limiter`，默认 200 次/分钟/IP |
| 业务级限流 | 登录 5 次/60 秒、注册 3 次/60 秒、验证码 1 次/60 秒且 10 次/天 |
| 安全响应头 | `X-Content-Type-Options: nosniff`、`X-Frame-Options: DENY`、`X-XSS-Protection`、`Cache-Control: no-store` |
| 代理头还原 | `TRUST_PROXY_HEADERS` 开启后使用 `ProxyFix` 还原真实 IP，避免限流退化 |
| 统一异常兜底 | 所有未捕获异常返回统一 JSON，不泄露堆栈 |

### 5.3 文件与路径安全

| 措施 | 说明 |
| --- | --- |
| 图片访问路径校验 | `routes/images.py` 用 `realpath` 限定在存储目录内，防路径穿越 |
| 上传文件类型校验 | `services/file_security.py` 校验 MIME 与扩展名匹配、危险扩展名黑名单（exe/bat/sh/js/ps1 等） |
| 上传体积限制 | 默认 50 MB（`FILE_UPLOAD_MAX_SIZE`） |
| 临时文件服务 | 使用不可猜的 UUID 作为标识，并做路径遍历防护 |

### 5.4 密钥与凭据保护

| 措施 | 说明 |
| --- | --- |
| 用户 API Key 加密存储 | AES-256-CBC，密钥来自 `USER_AI_KEY_ENCRYPTION_KEY` |
| 接口掩码返回 | 只返回前 4 位 + `****` + 后 4 位 |
| 邀请码双存储 | SHA-256 哈希用于查找 + AES 加密用于回显 |
| 密钥隔离 | 邀请码密钥与用户 Key 密钥强制不同 |
| SSRF 防护 | 校验用户填写的 `api_base`：必须是 http(s)、主机名可解析，且解析出的 IP 不得属于内网/保留/回环/链路本地/多播/云元数据地址（`169.254.169.254`）；放行代理 fake-ip 网段 `198.18.0.0/15` |

### 5.5 部署侧安全

| 措施 | 说明 |
| --- | --- |
| 容器非 root 运行 | 后端镜像创建 `appuser`（uid 1000）并以该用户运行 |
| 数据库/Redis 不对外暴露 | Compose 中仅绑定 `127.0.0.1` |
| 日志体积限制 | 单容器日志上限 10 MB × 3 个文件，避免撑满磁盘 |
| 健康检查 | 各服务均配置 healthcheck |

---

## 6. 发布前自查清单

### 6.1 敏感信息扫描

在仓库根目录执行以下检查，**全部应无真实密钥命中**：

```bash
# 1. 检查常见密钥前缀
grep -rnE "sk-[A-Za-z0-9]{20,}" --include="*.py" --include="*.ts" --include="*.vue" \
  --include="*.md" --include="*.sql" --include="*.example" . | grep -v node_modules

# 2. 检查硬编码的密钥赋值
grep -rniE "(api_key|password|secret|token)\s*[:=]\s*['\"][^'\"]{8,}['\"]" \
  --include="*.py" --include="*.ts" --include="*.vue" . | grep -v node_modules

# 3. 检查邮箱授权码与个人邮箱
grep -rnE "[a-zA-Z0-9._%+-]+@(qq|163|gmail|126)\.com" \
  --include="*.py" --include="*.sql" --include="*.md" --include="*.example" . | grep -v node_modules

# 4. 检查是否误提交 .env
git ls-files | grep -E "\.env$|\.env\.(local|production|dev)$"

# 5. 检查提交历史中是否出现过 .env
git log --all --full-history -- "*.env" ".env"
```

### 6.2 文件清单核对

```bash
# 查看将被提交的全部文件（应为源码、配置模板与文档，不含产物）
git status --short
git ls-files | wc -l

# 确认以下路径未被跟踪
git ls-files | grep -E "node_modules/|dist/|__pycache__/|uploads/|prototype/|\.env$" || echo "OK: 无产物被跟踪"
```

### 6.3 逐项核对表

| 检查项 | 通过标准 |
| --- | --- |
| 仓库无真实 API Key | `LLM_API_KEY` / `MULTIMODAL_API_KEY` / `IMAGE_GEN_API_KEY` 均为占位符 |
| 仓库无邮箱授权码 | `SMTP_PASSWORD` 在代码中无硬编码值 |
| 仓库无数据库密码 | 所有密码来自环境变量 |
| 仓库无个人邮箱 | 示例邮箱使用 `example.com` 或 `ecomai.local` 域名 |
| 仓库无明文密码 | `init_db.sql` 与文档中无明文密码 |
| 密钥默认值已弱化 | `config.py` 默认值为 `dev-only-*` 形式 |
| `.env` 未被跟踪 | `git ls-files` 无 `.env` 输出 |
| 模板文件为占位符 | `.env.example` / `.env.docker.example` 无真实值 |
| 运行产物已排除 | `uploads/`、`prototype/`、`*.log` 未被跟踪 |
| 前端无服务端密钥 | 前端源码与产物中无 API Key |
| 默认账号已处理 | 对外部署已改密或删除默认账号 |
| 示例数据已清理 | 示例兑换码、团队、公告、日志已按需清理 |
| LICENSE 存在 | 仓库根目录包含许可证文件 |

### 6.4 依赖安全检查（建议）

```bash
# 后端
pip install pip-audit
pip-audit -r auth-module-backend/requirements.txt

# 前端
cd ecom-ai-studio && npm audit --production
```

---

## 7. 密钥泄露应急处理

一旦确认密钥进入公开仓库或疑似泄露，按以下顺序处理：

### 7.1 立即轮换（最重要）

| 泄露类型 | 处理动作 |
| --- | --- |
| AI 服务 API Key | 登录服务商控制台**立即吊销**旧 Key 并生成新 Key |
| 邮箱授权码 | 在邮箱设置中重置 SMTP 授权码 |
| 数据库密码 | `ALTER USER 'root'@'%' IDENTIFIED BY '<new-password>';` 并更新 `.env` |
| `JWT_SECRET_KEY` | 更换密钥（会导致全部用户令牌失效，需重新登录） |
| `SECRET_KEY` | 更换密钥 |
| `INVITE_CODE_ENCRYPTION_KEY` | 更换后需重新生成团队邀请码 |
| `USER_AI_KEY_ENCRYPTION_KEY` | 更换后**存量用户 API Key 无法解密**，需通知用户重新填写 |
| 默认账号密码 | 修改密码或删除账号 |

### 7.2 清理 Git 历史

```bash
# 推荐使用 git-filter-repo
pip install git-filter-repo
git filter-repo --path auth-module-backend/.env --invert-paths

# 或使用 BFG Repo-Cleaner
java -jar bfg.jar --delete-files .env
git reflog expire --expire=now --all && git gc --prune=now --aggressive

# 强制推送（会重写历史，需通知所有协作者重新克隆）
git push --force-with-lease
```

> 历史重写后仍需执行 7.1 的轮换——**GitHub 的 fork、缓存与爬虫可能已经抓取过旧提交**。

### 7.3 排查滥用

检查服务商控制台的使用量与账单，确认是否存在异常调用；必要时先禁用 Key 再排查。

---

## 8. 生产环境加固建议

### 8.1 配置侧

| 建议 | 说明 |
| --- | --- |
| 关闭 debug | `FLASK_ENV=production` |
| 限制 CORS | `CORS_ALLOWED_ORIGINS` 设为具体域名，避免使用 `*` |
| 开启代理头还原 | `TRUST_PROXY_HEADERS=true`（位于 Nginx 之后时必须开启） |
| 调低限流阈值 | 按实际流量调整 `RATE_LIMIT_PER_MINUTE` |
| 强化密码策略 | `config.py` 中 `PASSWORD_MIN_LENGTH` 默认 6 且未强制复杂度（`PASSWORD_REQUIRE_UPPER` / `PASSWORD_REQUIRE_DIGIT` / `PASSWORD_REQUIRE_SPECIAL` 默认均为 `False`），对外部署建议开启并提高最小长度 |
| 密钥独立 | 每个环境使用独立密钥，不复用开发环境密钥 |
| 密钥托管 | 使用密钥管理服务（如云厂商 KMS / Secrets Manager）而非明文 `.env` |

### 8.2 网络侧

| 建议 | 说明 |
| --- | --- |
| 启用 HTTPS | 在 Nginx 或前置负载均衡终止 TLS |
| 数据库不暴露公网 | 仅允许应用所在网络访问 |
| Redis 设置密码 | 生产环境为 Redis 配置 `requirepass` 并同步更新 `REDIS_URL` |
| 限制管理后台访问 | 可对 `/api/v1/admin` 做 IP 白名单或额外网关校验 |

### 8.3 运维侧

| 建议 | 说明 |
| --- | --- |
| 定期轮换密钥 | 建立密钥轮换周期与流程 |
| 日志脱敏 | 避免在日志中输出完整请求体与密钥 |
| 监控异常调用 | 对 AI 调用量与失败率设置告警 |
| 备份加密 | 数据库与上传文件的备份应加密存储 |
| 最小权限 | 数据库账号按需授权，不使用 root 运行业务 |

---

## 附：相关文件索引

| 文件 | 说明 |
| --- | --- |
| [.env.docker.example](file:///d:/desktop/all_images/.env.docker.example) | Docker 部署环境变量模板 |
| [auth-module-backend/.env.example](file:///d:/desktop/all_images/auth-module-backend/.env.example) | 本地开发环境变量模板 |
| [.gitignore](file:///d:/desktop/all_images/.gitignore) | 仓库排除规则 |
| [auth-module-backend/config.py](file:///d:/desktop/all_images/auth-module-backend/config.py) | 后端配置定义 |
| [auth-module-backend/utils/security.py](file:///d:/desktop/all_images/auth-module-backend/utils/security.py) | 密码哈希、JWT、限流 |
| [auth-module-backend/utils/crypto.py](file:///d:/desktop/all_images/auth-module-backend/utils/crypto.py) | AES 加密工具 |
| [auth-module-backend/middleware/auth_middleware.py](file:///d:/desktop/all_images/auth-module-backend/middleware/auth_middleware.py) | 鉴权与 RBAC |
| [auth-module-backend/services/user_ai_provider_service.py](file:///d:/desktop/all_images/auth-module-backend/services/user_ai_provider_service.py) | BYOK 密钥加密与 SSRF 防护 |
| [docs/DATABASE.md](DATABASE.md) | 数据库表结构与默认账号处理 |
