# EcomAI_image_Studio

面向跨境电商场景的 AI 商品图生产平台。项目以「批量套图 + 专业精修 + AI 图片编辑」为核心，把商品图从拍摄、修图、多站点本地化到平台合规校验的整条链路收敛到一个 Web 工作台中。

后端采用 Flask + MySQL + Redis(ARQ) 的分层架构，前端采用 Vue 3 + TypeScript + Vite；图像生成、文档解析等长耗时链路全部走异步任务队列，通过 SSE 向前端实时推送进度。

---

## 目录

- [1. 项目介绍](#1-项目介绍)
- [2. 系统架构](#2-系统架构)
- [3. 目录结构](#3-目录结构)
- [4. 快速开始](#4-快速开始)
- [5. 功能模块一览](#5-功能模块一览)
- [6. 数据库](#6-数据库)
- [7. 安全与敏感信息](#7-安全与敏感信息)
- [8. 文档索引](#8-文档索引)

---

## 1. 项目介绍

### 1.1 开发背景

跨境卖家在商品图生产上面临三个具体问题：

1. **多站点适配成本高**：同一款商品要投放到 Amazon、Temu、Shopee、TikTok Shop、AliExpress、Ozon 等多个平台，每个平台对主图底色、商品占比、文字与水印的限制各不相同，人工逐张核对容易出错。
2. **多语言本地化繁琐**：不同站点需要不同的文案语言，部分站点（如日本、俄罗斯、阿拉伯语区）还涉及非拉丁字符，直接套用中文或英文文案会导致图片文字乱码或不合规。
3. **批量生产缺少一致性与对账能力**：同一批次几十上百张图需要保持统一的视觉风格，同时要能按张数精确计费、失败可退款、中断可续跑。

EcomAI_image_Studio 把上述问题拆解为可工程化的能力：**平台合规规则库**、**多语言/多站点提示词引擎**、**批次风格锁定**、**按分辨率计费的灵感币体系**，以及**可断点续跑的批量编排器**。

### 1.2 核心功能

| 功能域 | 能力说明 |
| --- | --- |
| AI 商品图 - 简单模式 | 上传商品图，选择站点与场景，自动生成成套商品图；支持「AI 帮写」多模态分析商品并回填中英双语卖点 |
| AI 商品图 - 专业模式 | 按图型（主图/场景图/细节图等 9 类）逐张生成提示词方案，支持对话式优化方案后再确认生图 |
| 批量套图编排 | 商品 × 站点 × 图型笛卡尔积展开，支持 TikTok 展示图组预设；批次级风格锁定、失败隔离、断点续跑、失败即时退款 |
| AI 图片编辑器 | 基于 Konva 的图层编辑器，支持裁剪/旋转/翻转/色彩调整，以及 AI 抠图、AI 换背景、AI 消除、AI 局部重绘、AI 高清放大；内置「规划 → 校验 → 执行」的 Agent，可用自然语言驱动多步编辑 |
| AI 工具箱 | 生图计划分析、图片合并、文生图、对话式生图、产品替换、AI 模特、模特商品图、反推提示词，共 8 个工具 |
| 平台合规 | 内置 6 大平台 × 3 类图型的规则库；生成前做提示词预校验（命中阻断项直接拦截且不计费），生成后可选做 AI 视觉合规审查并给出风险等级与整改建议 |
| 用户资产 | 历史记录、收藏、团队共享、团队钱包与转账、灵感币流水 |
| 团队与计费 | 团队创建/邀请码加入、个人与团队双钱包、充值套餐与兑换码、按功能与分辨率的定价配置 |
| 管理后台 | 仪表盘、定价方案管理、功能定价管理、兑换码管理、公告管理、团队消耗统计 |
| 自带模型通道（BYOK） | 用户可配置自己的 LLM / 多模态 / 生图服务商号池，开启后对应功能不扣灵感币 |

### 1.3 技术栈选型

**后端**

| 类别 | 选型 | 说明 |
| --- | --- | --- |
| 语言 / 框架 | Python 3.10+ / Flask 3.x | 蓝图分层，应用工厂模式，便于按模块扩展 |
| 数据库 | MySQL 8.0 | 业务数据持久化，InnoDB + utf8mb4 |
| 缓存 / 队列 | Redis 7 | ARQ 异步任务队列、任务状态 Hash、SSE 事件 Pub/Sub |
| 异步任务 | ARQ | 基于 asyncio 的轻量任务队列，与 Redis 原生配合 |
| 工作流编排 | LangGraph | 简单模式生图链路与编辑器 Agent 的状态图编排 |
| AI 能力 | OpenAI 兼容接口 | 文本 LLM、多模态理解、图像生成/编辑统一走兼容协议，可替换服务商 |
| 图像处理 | Pillow / rembg | 兜底抠图、缩放、蒙版合成等本地处理 |
| 鉴权 | PyJWT + bcrypt | JWT 无状态鉴权 + RBAC 装饰器，密码 bcrypt 加盐存储 |
| 生产服务 | Gunicorn (gthread) | SSE 长连接场景下 gthread 模型比同步模型更合适 |

**前端**

| 类别 | 选型 | 说明 |
| --- | --- | --- |
| 框架 | Vue 3.5 + TypeScript 5.6 | Composition API + `<script setup>` |
| 构建 | Vite 6 | 开发代理 `/api` → 后端 5001，生产产物 gzip/brotli 预压缩 |
| 状态管理 | Pinia 2 | `auth` / `workspace` / `editor` / `app` 四个 Store |
| 路由 | Vue Router 4 | 历史模式，登录守卫 |
| 样式 | Tailwind CSS 3 | 自定义品牌色板与动画 |
| 画布 | Konva + vue-konva | 图层编辑器与蒙版笔刷 |
| 表单校验 | vee-validate + zod | 登录/注册等表单校验 |
| 组件基元 | radix-vue + lucide-vue-next | 无样式组件基元与图标 |
| 测试 | Vitest + @vue/test-utils | 组件与纯函数单测 |

### 1.4 目标用户

- **跨境电商卖家与运营**：需要为多平台、多站点批量生产合规商品图。
- **跨境代运营 / 设计工作室**：以团队形式承接多个店铺的图片需求，需要团队钱包与共享历史。
- **独立站与 DTC 品牌**：需要风格统一的品牌视觉素材与精修能力。
- **二次开发者**：希望基于现成的多语言提示词引擎、合规规则库与异步生图链路做定制。

### 1.5 项目价值

- **合规前置**：把平台图片规则变成可执行的校验，违规提示词在扣费前即被拦截。
- **风格一致性**：批次级风格锁定让同批图片共享同一套色彩、光线与构图约束。
- **成本可控**：按分辨率/按次计费，预扣 - 失败退款 - 重试不重复扣费，账目可对平。
- **可扩展**：AI 通道、定价、合规规则、提示词模板均为数据驱动，新增平台或功能以配置为主。
- **可自建**：支持 BYOK，用户可接入自有模型服务商，降低平台侧成本。

---

## 2. 系统架构

```
                         ┌─────────────────────────────┐
   浏览器 ──────────────▶ │  frontend (Nginx :80)       │
                         │  · 托管 Vue 构建产物         │
                         │  · /api 反向代理             │
                         │  · /api/v1/sse/ 关闭缓冲     │
                         └──────────────┬──────────────┘
                                        │ /api
                                        ▼
                         ┌─────────────────────────────┐
                         │  backend (Gunicorn :5001)   │
                         │  · Flask 蓝图 / 鉴权 / 限流  │
                         │  · 迁移与种子数据（启动时）  │
                         │  · 任务提交（submit_task）   │
                         │  · SSE 进度流               │
                         └───┬──────────────────┬──────┘
                             │                  │
                 ┌───────────▼──────┐   ┌───────▼──────────────┐
                 │  MySQL 8.0       │   │  Redis 7             │
                 │  业务数据持久化   │   │  · ARQ 任务队列       │
                 │  25 张业务表      │   │  · 任务状态 Hash      │
                 └──────────────────┘   │  · task-events 频道   │
                             ▲          └───────┬──────────────┘
                             │                  │ 消费任务
                             │          ┌───────▼──────────────┐
                             └──────────│  worker (ARQ)        │
                              读写结果   │  生图 / 批量编排 /    │
                                        │  工具箱 / 编辑器 Agent│
                                        └───────┬──────────────┘
                                                │ 调用
                                        ┌───────▼──────────────┐
                                        │  外部 AI 服务         │
                                        │  LLM / 多模态 / 生图  │
                                        └──────────────────────┘
```

**关键设计**

- **前后端同域部署**：Nginx 托管静态资源并把 `/api` 反代到后端，避免跨域与额外鉴权配置。
- **异步优先**：所有超过数秒的操作（生图、文档解析、批量套图、编辑器工具与 Agent）都提交为 ARQ 任务，HTTP 接口只负责受理与查询。
- **状态双写**：任务状态同时写入 Redis Hash 与 `task-events:<task_id>` Pub/Sub 频道；SSE 建连时先读一次当前状态，再订阅增量事件。
- **迁移内建**：后端启动时自动执行 `migrations/` 下未执行过的 SQL，无需额外的迁移工具。

---

## 3. 目录结构

```
all_images/
├── README.md                     # 本文件
├── docs/                         # 项目文档
│   ├── QUICKSTART.md             # 快速部署指南
│   ├── MODULES.md                # 功能模块详解
│   ├── DATABASE.md               # 数据库搭建指南
│   └── SECURITY.md               # 安全规范说明
├── docker-compose.yml            # 一键编排：frontend / backend / worker / mysql / redis
├── .env.docker.example           # Docker 部署环境变量模板
├── .gitignore
│
├── auth-module-backend/          # 后端（Flask API + ARQ Worker 共用同一镜像）
│   ├── app.py                    # 应用工厂：配置、CORS、限流、迁移、种子、蓝图注册
│   ├── worker.py                 # ARQ Worker 入口与任务注册
│   ├── config.py                 # 配置管理（全部支持环境变量覆盖）
│   ├── gunicorn.conf.py          # 生产 WSGI 配置
│   ├── init_db.sql               # 数据库初始化脚本（建库建表 + 种子数据）
│   ├── Dockerfile
│   ├── .env.example              # 后端环境变量模板
│   ├── requirements.txt
│   ├── migrations/               # 增量迁移 SQL（按文件名顺序执行）
│   ├── models/                   # 数据模型（裸 SQL 访问层）
│   ├── routes/                   # 路由蓝图（18 个）
│   ├── controllers/              # 控制器（含编辑器 Agent 与工具）
│   ├── services/                 # 业务服务层
│   ├── workflows/                # LangGraph 生图工作流
│   ├── agents/                   # 专业模式方案优化 Agent
│   ├── prompts/                  # 提示词模板体系（zh / pro / 分品类）
│   ├── middleware/               # JWT 鉴权与 RBAC
│   ├── utils/                    # 密码、JWT、AES 加密工具
│   ├── config/dictionaries/      # 站点语言映射、场景环境映射
│   ├── scripts/                  # 运维脚本
│   └── tests/                    # 单元测试
│
└── ecom-ai-studio/               # 前端（Vue 3 + TypeScript）
    ├── index.html
    ├── vite.config.ts            # 开发代理、构建分包、gzip/brotli
    ├── tailwind.config.js
    ├── vitest.config.ts
    ├── Dockerfile                # 两阶段构建：node 构建 → nginx 托管
    ├── nginx.conf
    ├── BACKEND_DEVELOPMENT_GUIDE.md  # 前后端接口约定说明书
    └── src/
        ├── api/                  # 接口封装（统一请求客户端 + 各业务模块）
        ├── components/           # 组件（workspace / editor / common / layout / history / profile）
        ├── composables/          # useTaskSse 等组合式函数
        ├── lib/                  # 纯函数工具（批量预估、错误翻译、尺寸校验）
        ├── router/               # 路由表与登录守卫
        ├── stores/               # Pinia 状态
        ├── views/                # 页面（含 toolbox 8 个工具页与编辑器页）
        └── __tests__/            # 前端单测
```

---

## 4. 快速开始

### 4.1 Docker Compose 一键启动（推荐）

```bash
git clone <your-repo-url> EcomAI_image_Studio
cd EcomAI_image_Studio

# 1. 准备环境变量（务必按需修改密钥与密码）
cp .env.docker.example .env

# 2. 构建并启动全部服务
docker compose up -d --build

# 3. 查看状态与日志
docker compose ps
docker compose logs -f backend worker
```

启动完成后访问 `http://localhost:8080`，健康检查：

```bash
curl http://localhost:8080/healthz
curl http://localhost:8080/api/v1/health
```

### 4.2 本地开发启动

```bash
# 后端
cd auth-module-backend
pip install -r requirements.txt
cp .env.example .env          # 填写数据库与 AI 服务密钥
mysql -u root -p < init_db.sql
python app.py                 # API: http://localhost:5001
python worker.py              # 另开终端启动异步 Worker

# 前端
cd ../ecom-ai-studio
npm ci
npm run dev                   # http://localhost:5173
```

完整步骤、环境要求与验证方法见 **[docs/QUICKSTART.md](docs/QUICKSTART.md)**。

---

## 5. 功能模块一览

| 模块 | 后端入口 | 前端入口 |
| --- | --- | --- |
| 认证与权限 | `routes/auth.py`、`middleware/auth_middleware.py` | `views/LoginView.vue`、`stores/auth.ts` |
| AI 商品图（简单/专业） | `routes/generation.py`、`workflows/` | `views/WorkspaceView.vue`、`components/workspace/` |
| 批量套图编排 | `routes/batch_routes.py`、`services/batch_orchestrator.py` | `components/workspace/BatchPanel.vue` |
| AI 图片编辑器 | `routes/editor_routes.py`、`controllers/editor/` | `views/editor/EditorView.vue`、`components/editor/` |
| AI 工具箱（8 个工具） | `routes/toolbox.py`、`services/toolbox_service.py` | `views/toolbox/` |
| 平台合规 | `routes/compliance_routes.py`、`services/compliance_*.py` | `api/compliance.ts` |
| 多语言提示词引擎 | `services/multilang_engine.py`、`prompts/` | `components/workspace/SmartMode.vue` |
| 计费与钱包 | `services/feature_pricing_service.py`、`routes/purchase.py` | `views/PurchaseView.vue` |
| 团队协作 | `routes/team.py`、`services/team_service.py` | `views/TeamView.vue` |
| 历史与收藏 | `routes/history.py`、`routes/favorite.py` | `views/HistoryView.vue`、`views/FavoritesView.vue` |
| 自带模型通道（BYOK） | `routes/user_ai_provider.py`、`services/user_ai_provider_service.py` | `components/profile/AiProviderPanel.vue` |
| 管理后台 | `routes/admin.py` | `views/AdminView.vue` |

模块架构、核心算法与使用流程详见 **[docs/MODULES.md](docs/MODULES.md)**。

---

## 6. 数据库

- 数据库名默认 `ecomai_auth`，字符集 `utf8mb4` / `utf8mb4_unicode_ci`。
- 基础表与种子数据由 [init_db.sql](auth-module-backend/init_db.sql) 创建；增量变更由 [migrations/](auth-module-backend/migrations) 下的 SQL 在后端启动时自动补齐。
- 共 25 张业务表 + 1 张迁移追踪表 `_migrations`。

表结构说明、初始化步骤、迁移机制与配置示例详见 **[docs/DATABASE.md](docs/DATABASE.md)**。

---

## 7. 安全与敏感信息

- 仓库中**不包含**任何真实 API Key、邮箱授权码或数据库密码，所有密钥均通过环境变量注入。
- 环境变量模板：[.env.docker.example](.env.docker.example)（Docker 部署）、[auth-module-backend/.env.example](auth-module-backend/.env.example)（本地开发）。
- `.env`、`uploads/`、`node_modules/`、`dist/`、本地调研产物等已在 [.gitignore](.gitignore) 中排除。
- 数据库初始化脚本会写入仅供本地开发使用的示例账号，**上线前必须修改或删除**。

完整的敏感信息处理规范、环境变量清单与发布前自查清单详见 **[docs/SECURITY.md](docs/SECURITY.md)**。

---

## 8. 文档索引

| 文档 | 内容 |
| --- | --- |
| [docs/QUICKSTART.md](docs/QUICKSTART.md) | 环境要求、依赖安装、配置说明、启动命令、验证方法、常见问题 |
| [docs/MODULES.md](docs/MODULES.md) | 各功能模块的架构、核心算法、使用流程与界面说明 |
| [docs/DATABASE.md](docs/DATABASE.md) | 完整表结构、初始化 SQL、迁移机制、配置示例与备份建议 |
| [docs/SECURITY.md](docs/SECURITY.md) | 敏感信息处理规范、环境变量模板、发布前检查清单 |
| [ecom-ai-studio/BACKEND_DEVELOPMENT_GUIDE.md](ecom-ai-studio/BACKEND_DEVELOPMENT_GUIDE.md) | 前后端接口约定说明书（响应信封、错误码、分页等） |

---

## 许可证

发布前请在本仓库根目录补充 `LICENSE` 文件并确定许可证类型（如 MIT、Apache-2.0 或私有许可），同时在上方章节中同步说明。
