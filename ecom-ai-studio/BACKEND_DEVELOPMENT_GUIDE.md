# EcomAI Studio 后端开发准备说明书

> **文档版本**: v1.1
> **更新日期**: 2026-06-07
> **适用对象**: 后端开发团队
> **前端项目路径**: `d:\desktop\all_images\ecom-ai-studio`
> **后端项目路径**: `d:\desktop\all_images\auth-module-backend`
> **前端技术栈**: Vue 3.5 + TypeScript 5.6 + Vite 6.0 + Pinia + Vue Router 4.5
> **认证后端**: Python Flask 3.1 + PyMySQL + JWT + bcrypt

---

## 目录

1. [项目概述与技术架构](#1-项目概述与技术架构)
2. [页面路由与功能模块](#2-页面路由与功能模块)
3. [API接口设计规范](#3-api接口设计规范)
4. [数据模型设计](#4-数据模型设计)
5. [业务逻辑要点](#5-业务逻辑要点)
6. [认证与安全](#6-认证与安全)
7. [错误处理规范](#7-错误处理规范)
8. [后端技术选型建议](#8-后端技术选型建议)
9. [Mock数据迁移对照表](#9-mock数据迁移对照表)

---

## 1. 项目概述与技术架构

### 1.1 项目定位

**EcomAI Studio** 是一款 **AI 驱动的跨境电商视觉工作台**，核心功能围绕 AI 图像/视频生成展开，服务于跨境电商卖家的商品图、营销海报、视频短片等内容创作需求。

### 1.2 核心业务模式

| 模式 | 说明 | 适用场景 |
|------|------|----------|
| **Smart Mode（智能铺货）** | 批量生成商品展示图，支持多平台/地区/语言适配 | 快速上架、批量铺货 |
| **Pro Mode（专业精品）** | 单品精细化定制，支持多任务卡片、AI对话式提示词优化 | 品牌主图、精品详情页 |

### 1.3 前端技术栈详解

```
┌─────────────────────────────────────────────────────────────┐
│                      前端应用层 (Vue 3.5)                     │
├──────────────┬──────────────┬──────────────┬────────────────┤
│   状态管理    │    路由管理   │   UI框架     │   表单验证      │
│   Pinia 2.3  │ Vue Router   │ Radix Vue    │ Vee-validate  │
│              │   4.5        │ TailwindCSS  │ Zod Schema     │
├──────────────┴──────────────┴──────────────┴────────────────┤
│                        构建工具: Vite 6.0                    │
│                   开发端口: http://localhost:5173             │
│                   路径别名: @ → src                           │
└─────────────────────────────────────────────────────────────┘
```

**关键依赖版本：**

| 依赖 | 版本 | 用途 |
|------|------|------|
| vue | ^3.5.13 | 核心框架 (Composition API `<script setup>`) |
| pinia | ^2.3.0 | 状态管理 (3个Store) |
| vue-router | ^4.5.0 | 路由管理 (导航守卫鉴权) |
| radix-vue | ^1.9.12 | 无障碍UI组件库 |
| zod | ^3.24.1 | 运行时Schema校验 |
| lucide-vue-next | - | 图标库 |

### 1.4 整体架构图（前后端分离）

```
┌──────────────────┐         ┌──────────────────┐         ┌──────────────────┐
│                  │  HTTP/WS │                  │  API    │                  │
│   Vue 3 前端应用  │ ◄──────► │   后端 API 服务    │ ─────► │   AI 模型服务     │
│  (localhost:5173)│  RESTful │  (Node.js/Go/...) │  调用   │ (通义千问/GPT等)  │
│                  │  SSE/Poll │                  │        │                  │
└──────────────────┘         └────────┬─────────┘        └──────────────────┘
                                      │
                              ┌───────┴───────┐
                              ▼               ▼
                       ┌──────────┐    ┌──────────┐
                       │ PostgreSQL│    │   Redis   │
                       │ / MySQL  │    │(缓存/队列) │
                       └──────────┘    └──────────┘
                              │               │
                              ▼               ▼
                       ┌──────────┐    ┌──────────┐
                       │ 对象存储  │    │ 消息队列  │
                       │ (OSS/S3) │    │(异步任务) │
                       └──────────┘    └──────────┘
```

---

## 2. 页面路由与功能模块

### 2.1 完整路由表

| 路径 | 页面组件 | 布局 | 权限 | 功能说明 |
|------|----------|------|------|----------|
| `/login` | `LoginView.vue` | 独立布局 (`guest`) | 公开 | 登录/注册双Tab |
| `/` | `HomeView.vue` | `AppLayout` | 已登录 | 首页/全局搜索/灵感案例 |
| `/workspace` | `WorkspaceView.vue` | `AppLayout` | 已登录 | AI图像生成工作台（核心页面）|
| `/history` | `HistoryView.vue` | `AppLayout` | 已登录 | 生成历史记录查看 |
| `/favorites` | `FavoritesView.vue` | `AppLayout` | 已登录 | 收藏图片管理 |
| `/team` | `TeamView.vue` | `AppLayout` | 已登录 | 团队管理（创建/加入/成员）|
| `/purchase` | `PurchaseView.vue` | `AppLayout` | 已登录 | 充值中心（钱包/套餐/兑换码）|
| `/admin` | `AdminView.vue` | `AppLayout` | 管理员 | 管理后台（5个子模块）|
| `/poster` | `PosterView.vue` | `AppLayout` | 已登录 | AI营销海报生成 |
| `/video` | `VideoView.vue` | `AppLayout` | 已登录 | AI视频短片生成 |
| `/toolbox` | `ToolboxView.vue` | `AppLayout` | 已登录 | AI图片编辑工具箱 |

**路由守卫逻辑（前端已实现）：**
```typescript
// src/router/index.ts — beforeEach 导航守卫
router.beforeEach((to, _from, next) => {
  const isLoggedIn = localStorage.getItem('ecomai_logged_in') === 'true'
  if (!to.meta.guest && !isLoggedIn) {
    next('/login')  // 未登录跳转登录页
  } else if (to.meta.admin && !isAdmin) {
    next('/')       // 非管理员禁止访问
  } else {
    next()
  }
})
```

> **注意**: 当前前端使用 `localStorage` 存储登录状态。后端实现时需替换为 JWT Token 或 Session 鉴权方案。

#### 2.2.2 工作台模块（Smart Mode / Pro Mode）— 核心页面

**对应文件**: `src/views/WorkspaceView.vue`, `src/components/workspace/*.vue`, `src/stores/workspace.ts`

这是整个系统最复杂的页面，采用左右分栏布局：

```
┌─────────────────────────────────────────────────────────────┐
│  WorkspaceView                                               │
├──────────────────┬──────────────────────────────────────────┤
│   AssetPanel     │           CanvasArea                      │
│   (340px 固定宽)  │                                          │
│                  │                                          │
│  ┌────────────┐  │   ┌──────────────────────────────────┐   │
│  │ 模式切换    │  │   │  状态栏: 进度 / 结果计数          │   │
│  │ Smart/Pro  │  │   ├──────────────────────────────────┤   │
│  ├────────────┤  │   │                                  │   │
│  │ 商品图上传  │  │   │   ImageCard Grid                 │   │
│  │ (最多10张)  │  │   │   (收藏/下载/预览/重试)          │   │
│  ├────────────┤  │   │                                  │   │
│  │ 参考图上传  │  │   │                                  │   │
│  │ (strength) │  │   └──────────────────────────────────┘   │
│  ├────────────┤  │                                          │
│  │ SmartMode  │  │   全屏预览模态框 (Teleport to body)       │
│  │ 或 ProMode │  │                                          │
│  ├────────────┤  │                                          │
│  │ 成本预估    │  │                                          │
│  │ 支付选择    │  │                                          │
│  │ [生成按钮]  │  │                                          │
│  └────────────┘  │                                          │
└──────────────────┴──────────────────────────────────────────┘
```

**Smart Mode 表单字段：**

| 字段 | 类型 | 可选值 | 说明 |
|------|------|--------|------|
| platform | string | amazon, ebay, shopify, aliexpress, temu, shein, etsy, walmart, lazada, shopee, tiktok, alibaba, rakuten, mercari, wish, custom + 自定义输入 | 目标电商平台 |
| region | string | us, uk, de, fr, jp, ca, au, it, es, nl, se, br, mx, in, kr, tw, hk, sg, my, th, id, vn, ph, sa, ae, custom + 自定义输入 | 目标销售地区 |
| language | string | en, zh, ja, ko, de, fr, es, it, pt, ru, ar, th, vi, ms, id, fil, hi, tr, nl, sv, custom + 自定义输入 | 图片文字语言 |
| aspectRatio | string | '1:1', '3:4', '4:3', '16:9', 'custom' | 输出图片比例 |
| resolution | string \| number | '1K'(1024), '2K'(2048), '4K'(4096), 自定义数字 | 分辨率预算 |
| productDescription | textarea | 自由文本 | 商品信息描述（产品名称/目标受众/卖点等），支持"AI帮写" |
| slots | object[] | 白底图/场景图/卖点图/其他 四组，每组可配置多个slot | 套图结构 |

**Pro Mode 额外字段（在Smart Mode基础上扩展）：**

| 字段 | 类型 | 说明 |
|------|------|------|
| taskCards | ProTaskCard[] | 生图任务卡片列表（可增删）|
| taskCard.name | string | 任务名称 |
| taskCard.productImages | ProductImage[] | 该任务使用的商品图 |
| taskCard.referenceImage | ReferenceImage? | 参考图（含strength 0-100）|
| taskCard.promptScheme | string | 提示词方案（原始）|
| taskCard.polishedPrompt | string | AI润色后的提示词 |
| taskCard.aspectRatio | AspectRatio | 单独的比例设置 |
| proConfig.lighting | LightingStyle | 光影风格: natural/studio-soft/warm-dusk/cool-tech |
| proConfig.cameraAngle | CameraAngle | 拍摄角度: eye-level/top-down/low-45 |
| proConfig.zhTags | string[] | 中文标签列表 |
| proConfig.promptHistory | string[] | 提示词修改历史 |

**Pro Mode 特色功能 — AI分析整合对话框：**
- 点击"分析整合"按钮 → 收集所有taskCards配置 → 后端LLM聚合分析 → 返回概览+建议
- 支持对话式交互：用户提出修改建议 → LLM返回优化后的配置建议
- 消息格式: `{ id, role: 'user'|'assistant', content, timestamp }`

#### 2.2.3 内容生成模块

**AI营销海报 (`/poster`) — PosterView.vue**

| 字段 | 类型 | 可选值 | 说明 |
|------|------|--------|------|
| mode | string | 'template' \| 'free' | 模板模式/自由创作 |
| description | textarea | 自由文本 | 海报文字描述 |
| templateStyle | string | 6种模板风格 | 视觉风格选择 |
| canvasSize | string | '1:1','3:4','9:16','16:9','4:3' | 画布尺寸 |
| title | string | - | 主标题 |
| subtitle | string | - | 副标题 |
| ctaText | string | - | CTA行动号召文案 |
| brandColor | string | - | 品牌主色 |
| textStyle | string | - | 文字风格 |
| referenceImage | File? | - | 参考图上传 |
| **单价** | - | - | **每张 8 灵感币** |

**AI视频短片 (`/video`) — VideoView.vue**

| 字段 | 类型 | 可选值 | 说明 |
|------|------|--------|------|
| productImages | ProductImage[] | 至少1张 | 商品图片 |
| videoTemplate | string | 6种模板 | 商品展示/开箱体验/生活场景/对比评测/电影质感/社媒爆款 |
| videoSize | string | '16:9','9:16','1:1','9:16-story' | 尺寸预设 |
| cameraStyle | string | 多种运镜风格 | 运镜风格 |
| duration | number | 5-30秒 | 时长滑块 |
| bgMusic | string | - | 背景音乐选择 |
| **单价** | - | - | **每条 15 灵感币** |

**AI工具箱 (`/toolbox`) — ToolboxView.vue**

三栏布局：工具栏(280px) + 画布 + 参数面板(300px)

12个工具分6类：

| 分类 | 工具列表 | 额外费用 |
|------|----------|----------|
| 基础 | 裁切、旋转、翻转 | 免费 |
| 调整 | 亮度、对比度、饱和度、清晰度 | 免费（客户端处理）|
| 增强 | AI增强 | 5币 |
| 修复 | 去水印、消除物体 | 去水印3币/消除物体4币 |
| 裁切 | 自由裁切 | 免费 |
| 变换 | 透视校正、畸变修复 | 免费 |

部分AI工具需要调用后端API处理，基础调整操作在前端Canvas完成。

#### 2.2.4 用户资产模块

**历史记录 (`/history`) — HistoryView.vue**
- 批次列表展示（时间倒序）
- 筛选条件：搜索关键词 + 生成模式(Smart/Pro) + 状态(success/partial/failed)
- 批次详情展开：生图参数 + 生成结果网格
- 操作：克隆配置再次生成、删除批次

**收藏夹 (`/favorites`) — FavoritesView.vue**
- 网格展示收藏的图片
- 操作：下载原图、基于收藏配置再次生成、取消收藏

**充值中心 (`/purchase`) — PurchaseView.vue**
- 个人/团队钱包切换显示余额
- 兑换码输入兑换
- 定价方案选择（网格卡片 + 底部浮动确认栏）
- 支付确认弹窗
- 支付成功提示

#### 2.2.5 团队协作模块 (`/team`) — TeamView.vue

**Tab切换：个人空间 / 团队空间**

个人空间：
- 个人信息展示
- 创建团队入口

团队空间（选中团队后）：
- 团队基本信息（名称、类目、邀请码、钱包余额）
- 成员列表（Owner可移除成员）
- 近7天消耗图表数据
- Owner专属操作：生成邀请码、充值团队池

**创建团队弹窗：** 名称 + 类目选择
**加入团队弹窗：** 6位邀请码输入

#### 2.2.6 管理后台模块 (`/admin`) — AdminView.vue

5个Tab子模块：

| Tab | 功能 | 数据需求 |
|-----|------|----------|
| **监控仪表盘** | 在线人数、今日灵感币消耗、Qwen/GPT API成功率对比、每小时请求量趋势图、失败趋势、模型健康度 | 实时/近24h聚合数据 |
| **定价管理** | 套餐方案的增删改查、上下架、排序 | PricingPlan CRUD |
| **团队消耗** | 各团队消耗统计表格、排序 | TeamConsumption 列表 |
| **兑换码管理** | 生成兑换码、按状态筛选、删除 | RedemptionCode CRUD |
| **公告管理** | 发布公告、编辑、上下架、删除 | Announcement CRUD |

---

## 3. API接口设计规范

### 3.1 通用约定

| 约定项 | 规范 |
|--------|------|
| Base URL | `/api/v1` |
| 认证方式 | `Authorization: Bearer <jwt_token>` （除登录/注册/公开接口外均需携带）|
| Content-Type | `application/json` |
| 请求编码 | UTF-8 |
| 分页参数 | `page`(从1开始), `pageSize`(默认20, 最大100) |
| 时间格式 | ISO 8601: `2026-06-06T10:30:00Z` |
| ID格式 | UUID v4 (字符串) |
| 布尔值 | JSON boolean `true`/`false` |

**统一响应格式：**

```typescript
// 成功响应
interface ApiResponse<T> {
  code: number        // 0 表示成功
  message: string     // "success"
  data: T             // 业务数据
}

// 分页响应
interface PaginatedResponse<T> extends ApiResponse<T[]> {
  pagination: {
    page: number
    pageSize: number
    total: number
    totalPages: number
  }
}

// 错误响应
interface ApiError {
  code: number        // 非0错误码
  message: string     // 错误描述
  details?: any       // 详细错误信息（校验失败时为字段级错误）
}
```

### 3.2 认证接口

#### POST /api/v1/auth/login — 登录

**请求：**
```json
{
  "email": "user@example.com",
  "code": "123456",       // 验证码（验证码登录模式）
  "password": "xxx"        // 密码（密码登录模式，二选一）
}
```
**响应：**
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "token": "eyJhbGciOiJIUzI1NiIs...",
    "user": {
      "id": "uuid",
      "email": "user@example.com",
      "avatar": "https://...",
      "personalPoints": 100,
      "role": "user",
      "createdAt": "2026-01-01T00:00:00Z"
    }
  }
}
```

#### POST /api/v1/auth/register — 注册

**请求：**
```json
{
  "email": "user@example.com",
  "password": "SecurePass123!",
  "code": "123456"
}
```
**响应：** 同登录（注册成功自动登录并返回token）

#### POST /api/v1/auth/send-code — 发送验证码

**请求：**
```json
{ "email": "user@example.com" }
```
**响应：**
```json
{ "code": 0, "message": "验证码已发送" }
```

> **约束**: 同一邮箱60秒内只能发送一次验证码；每日最多10次。

#### POST /api/v1/auth/logout — 登出

**请求头:** `Authorization: Bearer <token>`
**响应：** `{ "code": 0, "message": "success" }`

#### GET /api/v1/auth/me — 获取当前用户信息

**请求头:** `Authorization: Bearer <token>`
**响应：** 返回完整 User 对象（同登录响应中的 user）

---

### 3.3 用户与资产接口

#### GET /api/v1/user/profile — 获取用户资料

**响应：**
```json
{
  "code": 0,
  "data": {
    "id": "uuid",
    "email": "user@example.com",
    "avatar": "https://...",
    "personalPoints": 150,
    "role": "user",
    "createdAt": "2026-01-01T00:00:00Z"
  }
}
```

#### PUT /api/v1/user/profile — 更新用户资料

**请求：**
```json
{
  "avatar": "https://..."  // 头像URL（需先上传获取URL）
}
```

#### GET /api/v1/user/balance — 获取余额信息

**查询参数:** `wallet=personal|team&teamId=uuid`（可选）

**响应：**
```json
{
  "code": 0,
  "data": {
    "walletType": "personal",
    "balance": 150,
    "teamBalance": null  // 当wallet=team时返回团队池余额
  }
}
```

#### GET /api/v1/user/points-records — 获取灵感币流水

**查询参数:**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| wallet | string | 否 | personal/team，默认personal |
| teamId | string | 否 | 团队ID（wallet=team时必填）|
| type | string | 否 | consume/refund/bonus/topup 筛选 |
| page | number | 否 | 页码，默认1 |
| pageSize | number | 否 | 每页条数，默认20 |

**响应：** `PaginatedResponse<PointsRecord>`

---

### 3.4 团队接口

#### GET /api/v1/teams — 获取我的团队列表

**响应：**
```json
{
  "code": 0,
  "data": [
    {
      "id": "uuid",
      "name": "跨境电商A组",
      "category": "3C数码",
      "inviteCode": "ABC123",
      "ownerId": "uuid",
      "memberCount": 5,
      "poolBalance": 500
    }
  ]
}
```

#### POST /api/v1/teams — 创建团队

**请求：**
```json
{
  "name": "新团队名称",
  "category": "服装配饰"
}
```

#### POST /api/v1/teams/join — 加入团队

**请求：**
```json
{ "inviteCode": "ABC123" }
```

#### GET /api/v1/teams/:teamId/members — 获取团队成员列表

**响应：**
```json
{
  "code": 0,
  "data": [
    { "id": "uuid", "email": "owner@mail.com", "role": "Owner", "joinedAt": "2026-01-01T00:00:00Z" },
    { "id": "uuid", "email": "member@mail.com", "role": "Member", "joinedAt": "2026-02-01T00:00:00Z" }
  ]
}
```

#### DELETE /api/v1/teams/:teamId/members/:memberId — 移除团队成员

**权限:** 仅Owner可操作

#### GET /api/v1/teams/:teamId/consumption — 获取团队消耗统计

**查询参数:** `period=week|month`（可选，默认week）

**响应：**
```json
{
  "code": 0,
  "data": {
    "teamId": "uuid",
    "teamName": "团队名",
    "category": "3C数码",
    "memberCount": 5,
    "totalCoinsConsumed": 1200,
    "todayCoinsConsumed": 50,
    "weeklyCoinsConsumed": 350,
    "monthlyCoinsConsumed": 800
  }
}
```

---

### 3.5 AI图像生成接口（核心）

#### POST /api/v1/generate — 提交生成任务

**这是最核心的接口，触发AI图像生成流程。**

**请求：**
```json
{
  "mode": "smart",
  "walletType": "personal",
  "teamId": null,

  // === Smart Mode 特有字段 ===
  "productImages": ["https://oss.url/img1.jpg", "https://oss.url/img2.jpg"],
  "referenceImage": {
    "url": "https://oss.url/ref.jpg",
    "strength": 70
  },
  "sceneStyle": "amazon-white",
  "platform": "amazon",
  "region": "us",
  "language": "en",
  "aspectRatio": "1:1",
  "resolution": "2K",
  "customWidth": 2048,
  "customHeight": 2048,
  "productDescription": "一款时尚的蓝牙耳机...",
  "slots": [
    { "type": "white-bg", "count": 3 },
    { "type": "scene", "count": 5 },
    { "type": "highlight", "count": 2 },
    { "type": "other", "count": 1 }
  ],

  // === Pro Mode 特有字段（mode="pro"时使用）===
  "proConfig": {
    "rawPrompt": "原始提示词...",
    "polishedPrompt": "润色后提示词...",
    "zhTags": ["蓝牙耳机", "无线", "降噪"],
    "lighting": "studio-soft",
    "cameraAngle": "eye-level",
    "aspectRatio": "1:1"
  },
  "taskCards": [
    {
      "name": "主图-白底",
      "productImages": ["https://oss.url/img1.jpg"],
      "referenceImage": { "url": "...", "strength": 70 },
      "promptScheme": "专业白底产品摄影...",
      "polishedPrompt": "AI优化后的提示词...",
      "aspectRatio": "1:1"
    }
  ]
}
```

**响应（同步 — 立即返回batchId）：**
```json
{
  "code": 0,
  "message": "任务已提交",
  "data": {
    "batchId": "batch-uuid-xxxx",
    "estimatedCost": 35,
    "deductedFrom": "personal",
    "remainingBalance": 115,
    "estimatedTimeSeconds": 80,
    "taskCount": 5
  }
}
```

**业务流程：**
1. 校验参数合法性（图片数量≤10、尺寸合规、余额充足）
2. **预扣费**：从指定钱包扣除预计费用
3. 创建批次记录（status: processing）
4. 将任务投入消息队列
5. 异步调用AI模型生成图像
6. 生成完成后回调更新结果（或通过SSE/WebSocket推送进度）

#### GET /api/v1/generate/:batchId/status — 查询生成状态

**推荐使用 SSE (Server-Sent Events) 方式实时推送：**

**SSE端点:** `GET /api/v1/generate/:batchId/stream`

**SSE事件流：**
```
event: progress
data: {"batchId":"xxx","current":2,"total":5,"status":"processing"}

event: image_ready
data: {"imageId":"img-uuid","url":"https://...","status":"success"}

event: image_failed
data: {"imageId":"img-uuid","errorMsg":"模型超时","status":"failed"}

event: complete
data: {"batchId":"xxx","status":"partial","totalCount":5,"successCount":4,"failedCount":1}
```

**轮询备选方案（兼容性考虑）：**

**GET /api/v1/generate/:batchId/status**

**响应：**
```json
{
  "code": 0,
  "data": {
    "batchId": "xxx",
    "status": "processing",        // processing | success | partial | failed
    "progress": { "current": 3, "total": 5 },
    "images": [
      { "id": "img-uuid", "url": "https://...", "status": "success" },
      { "id": "img-uuid", "status": "processing" },
      { "id": "img-uuid", "status": "failed", "errorMsg": "内容审核不通过" }
    ]
  }
}
```

#### POST /api/v1/generate/:batchId/retry — 重试失败的图片

**请求：**
```json
{ "imageIds": ["img-uuid-1", "img-uuid-2"] }
```

**说明:** 仅重试指定失败的图片，重新扣费（仅对重试的数量扣费）

#### POST /api/v1/generate/pro/analyze — Pro Mode AI分析整合

**请求：**
```json
{
  "taskCards": [...],       // 所有任务卡片配置
  "conversationHistory": [] // 对话历史（首次为空数组）
}
```

**响应：**
```json
{
  "code": 0,
  "data": {
    "overview": "您共配置了3个生图任务，覆盖白底图和场景图两种类型...",
    "suggestions": [
      "建议任务1增加自然光光影效果以提升真实感",
      "任务2和任务3的构图角度过于相似，建议差异化..."
    ],
    "reply": "分析结果的自然语言回复...",
    "optimizedConfigs": [...]  // 可选：优化后的配置建议
  }
}
```

> **注意**: 此接口需集成LLM服务（OpenAI API / 通义千问），将用户配置作为context传入。

---

### 3.6 文件上传接口

#### POST /api/v1/upload/image — 上传图片

**Content-Type:** `multipart/form-data`

**表单字段:**
| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| file | File | 是 | 图片文件 |
| type | string | 否 | product/reference，默认product |

**文件约束（前端已校验，后端必须复检）：**
- 格式: JPG / PNG / WebP
- 大小: ≤ 10MB
- 数量: 单次1张（批量需多次调用，上限10张）

**响应：**
```json
{
  "code": 0,
  "data": {
    "url": "https://oss.bucket/path/to/file.jpg",
    "fileId": "file-uuid",
    "width": 1024,
    "height": 768,
    "size": 245000,
    "format": "jpeg"
  }
}
```

**后端处理后需执行：**
1. 格式/大小校验
2. 图片安全扫描（违规内容检测）
3. 上传至OSS并返回可访问URL
4. 记录文件元信息

---

### 3.7 历史记录接口

#### GET /api/v1/history — 获取历史批次列表

**查询参数:**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| keyword | string | 否 | 搜索关键词 |
| mode | string | 否 | smart/pro 筛选 |
| status | string | 否 | success/partial/failed 筛选 |
| page | number | 否 | 默认1 |
| pageSize | number | 否 | 默认20 |

**响应：** `PaginatedResponse<HistoryBatch>`

#### GET /api/v1/history/:batchId — 获取批次详情

**响应：** 完整 HistoryBatch 对象（含 generatedImages 数组）

#### DELETE /api/v1/history/:batchId — 删除历史批次

**响应：** `{ "code": 0 }`

#### POST /api/v1/history/:batchId/clone — 克隆批次配置

**响应：** 返回 GenerationConfig 对象（用于填充工作区表单）

---

### 3.8 收藏接口

#### GET /api/v1/favorites — 获取收藏列表

**查询参数:** `page`, `pageSize`

**响应：** `PaginatedResponse<FavoriteItem>`

#### POST /api/v1/favorites — 添加收藏

**请求：**
```json
{
  "imageUrl": "https://oss.url/generated.jpg",
  "batchId": "batch-uuid",
  "config": { ... }  // 生成时的配置快照
}
```

#### DELETE /api/v1/favorites/:favoriteId — 取消收藏

**响应：** `{ "code": 0 }`

---

### 3.9 支付与充值接口

#### GET /api/v1/pricing-plans — 获取定价方案列表

**查询参数:** `isActive=true`（可选，仅返回上架中的方案）

**响应：**
```json
{
  "code": 0,
  "data": [
    {
      "id": "uuid",
      "name": "入门包",
      "price": 9.9,
      "coins": 100,
      "bonusCoins": 20,
      "isActive": true,
      "sortOrder": 1,
      "createdAt": "2026-01-01T00:00:00Z"
    }
  ]
}
```

#### POST /api/v1/purchase/create-order — 创建支付订单

**请求：**
```json
{
  "planId": "uuid",
  "walletType": "personal",
  "teamId": null
}
```

**响应：**
```json
{
  "code": 0,
  "data": {
    "orderId": "order-uuid",
    "planName": "入门包",
    "amount": 9.9,
    "coins": 120,            // 含赠送
    "paymentUrl": "https://pay.gateway.com/...",  // 支付网关跳转链接
    "expiresAt": "2026-06-06T10:35:00Z"            // 15分钟过期
  }
}
```

#### POST /api/v1/purchase/pay-confirm — 支付结果确认（回调）

**请求（支付网关回调）：**
```json
{
  "orderId": "order-uuid",
  "transactionId": "tx-xxx",
  "status": "success",  // success / failed
  "paidAt": "2026-06-06T10:34:00Z"
}
```

> **重要**: 此接口需做签名验签，防止伪造支付回调。

#### POST /api/v1/purchase/redeem — 兑换码充值

**请求：**
```json
{
  "code": "WELCOME2026",
  "walletType": "personal",
  "teamId": null
}
```

**响应：**
```json
{
  "code": 0,
  "data": {
    "coinsAdded": 50,
    "newBalance": 200,
    "codeInfo": { "code": "WELCOME2026", "originalCoins": 50 }
  }
}
```

**错误情况：**
- 兑换码不存在 → `4001`
- 兑换码已使用 → `4002`
- 兑换码已过期 → `4003`

---

### 3.10 内容生成接口（海报/视频/工具箱）

#### POST /api/v1/poster/generate — 生成营销海报

**请求：**
```json
{
  "mode": "template",
  "description": "夏季促销活动海报...",
  "templateStyle": "minimal-elegant",
  "canvasSize": "16:9",
  "title": "夏日大促",
  "subtitle": "全场低至5折",
  "ctaText": "立即抢购",
  "brandColor": "#FF6B6B",
  "textStyle": "modern-bold",
  "referenceImageUrl": "https://...",
  "walletType": "personal"
}
```

**响应：** 同 generate 接口的 batchId 结构
**计费:** 每张 8 灵感币

#### POST /api/v1/video/generate — 生成视频短片

**请求：**
```json
{
  "productImages": ["https://..."],
  "videoTemplate": "unboxing",
  "videoSize": "16:9",
  "cameraStyle": "dynamic",
  "duration": 15,
  "bgMusic": "upbeat-pop",
  "walletType": "personal"
}
```

**响应：** 返回 taskId + SSE推送进度
**计费:** 每条 15 灵感币

#### POST /api/v1/toolbox/process — AI工具箱处理

**请求：**
```json
{
  "tool": "remove-bg",          // 工具标识
  "imageUrl": "https://...",    // 待处理图片
  "params": {},                 // 工具特定参数
  "walletType": "personal"
}
```

**支持的AI工具及费用：**

| tool标识 | 中文名 | 费用(灵感币) |
|----------|--------|-------------|
| enhance | AI增强 | 5 |
| remove-watermark | 去水印 | 3 |
| remove-object | 消除物体 | 4 |

> 注意: 亮度/对比度/饱和度等基础调整工具在前端Canvas完成，无需调用后端。

**响应：**
```json
{
  "code": 0,
  "data": {
    "resultUrl": "https://oss.result/processed.png",
    "cost": 2,
    "remainingBalance": 148
  }
}
```

---

### 3.11 管理后台接口

> **所有管理接口需 admin 角色权限**

#### GET /api/v1/admin/stats/dashboard — 仪表盘统计数据

**响应：**
```json
{
  "code": 0,
  "data": {
    "onlineUsers": 128,
    "todayPoints": 3456,
    "qwenSuccessRate": 96.5,
    "gptSuccessRate": 94.2,
    "hourlyRequests": [
      { "hour": "00:00", "count": 45 },
      { "hour": "01:00", "count": 32 }
      // ... 24小时数据
    ],
    "failureTrend": [
      { "time": "10:00", "count": 3 },
      // ...
    ],
    "modelHealth": {
      "qwen": { "avgLatency": 2300, "errorRate": 3.5, "status": "healthy" },
      "gpt": { "avgLatency": 3100, "errorRate": 5.8, "status": "warning" }
    }
  }
}
```

#### GET /api/v1/admin/pricing-plans — 定价方案列表

**完整CRUD:**
- `POST /api/v1/admin/pricing-plans` — 创建
- `PUT /api/v1/admin/pricing-plans/:id` — 更新
- `DELETE /api/v1/admin/pricing-plans/:id` — 删除（软删除）

#### GET /api/v1/admin/consumptions — 团队消耗统计

**查询参数:** `sortBy=totalCoinsConsumed&sortOrder=desc&page=1&pageSize=20`

**响应：** `PaginatedResponse<TeamConsumption>`

#### 兑换码管理

- `POST /api/v1/admin/redemption-codes` — 批量生成兑换码
  ```json
  { "count": 10, "coins": 50, "expiresInDays": 30, "remark": "618活动" }
  ```
- `GET /api/v1/admin/redemption-codes` — 列表（支持 isUsed, isActive 筛选）
- `DELETE /api/v1/admin/redemption-codes/:id` — 删除

#### 公告管理

- `POST /api/v1/admin/announcements` — 发布公告
  ```json
  { "title": "系统维护通知", "content": "...", "type": "important", "isPinned": true, "expiresAt": "2026-07-01T00:00:00Z" }
  ```
- `PUT /api/v1/admin/announcements/:id` — 编辑
- `PATCH /api/v1/admin/announcements/:id/toggle-status` — 上下架
- `DELETE /api/v1/admin/announcements/:id` — 删除

---

### 3.12 公共接口（无需认证）

#### GET /api/v1/styles — 获取场景风格列表

**响应：** StyleCard[]（9种预设风格）

#### GET /api/v1/inspirations — 获取灵感案例列表

**查询参数:** `tag`, `keyword`, `page`, `pageSize`

**响应：** `PaginatedResponse<InspirationItem>`

#### GET /api/v1/announcements/public — 获取公开公告

**响应：** Announcement[]（仅 isActive=true 且未过期的）

#### GET /api/v1/features — 获取功能入口卡片

**响应：** FeatureCard[]（4个功能入口）

---

## 4. 数据模型设计

### 4.1 ER关系图

```
┌──────────┐       ┌──────────────┐       ┌──────────┐
│   User   │──1:N──│ TeamMember   │──N:1──│   Team   │
│──────────│       │──────────────│       │──────────│
│ id (PK)  │       │ id (PK)      │       │ id (PK)  │
│ email    │       │ userId (FK)  │       │ name     │
│ avatar   │       │ teamId (FK)  │       │ category │
│ password │       │ role         │       │ inviteCode│
│ personal_│       │ joinedAt     │       │ ownerId(FK)│
│  points  │       └──────────────┘       │ pool_    │
│ role     │                               │ balance  │
│ created_at│                              └────┬─────┘
└─────┬────┘                                   │
      │                                        │
      │ 1:N                                    │ 1:N
      ▼                                        ▼
┌──────────────┐                       ┌──────────────┐
│ HistoryBatch │                       │ PointsRecord │
│──────────────│                       │──────────────│
│ id (PK)      │                       │ id (PK)      │
│ userId (FK)  │                       │ userId (FK)  │
│ timestamp    │                       │ amount       │
│ status       │                       │ type         │
│ config (JSON)│                       │ sourceWallet │
│ input_images │                       │ teamId (FK)  │
│ (JSON)       │                       │ description  │
└──────┬───────┘                       │ createdAt    │
       │ 1:N                          └──────────────┘
       ▼
┌────────────────┐
│ GeneratedImage │
│────────────────│
│ id (PK)        │
│ batchId (FK)   │
│ taskId         │
│ url            │
│ status         │
│ errorMsg       │
│ favorited      │
└───────┬────────┘
        │ N:1
        ▼
┌──────────────┐
│ FavoriteItem │
│──────────────│
│ id (PK)      │
│ imageUrl     │
│ batchId (FK) │
│ config (JSON)│
│ createdAt    │
└──────────────┘
```

### 4.2 核心实体表结构定义

#### users 表

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | UUID | PK, NOT NULL | 用户唯一标识 |
| email | VARCHAR(255) | UNIQUE, NOT NULL | 登录邮箱 |
| password_hash | VARCHAR(255) | NOT NULL | bcrypt加密密码 |
| avatar | VARCHAR(500) | NULLABLE | 头像URL |
| personal_points | INTEGER | DEFAULT 0, CHECK >= 0 | 个人钱包灵感币余额 |
| role | ENUM('user','admin') | DEFAULT 'user' | 用户角色 |
| created_at | TIMESTAMP | DEFAULT NOW() | 创建时间 |
| updated_at | TIMESTAMP | DEFAULT NOW() | 更新时间 |

#### teams 表

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | UUID | PK, NOT NULL | 团队ID |
| name | VARCHAR(100) | NOT NULL | 团队名称 |
| category | VARCHAR(50) | NOT NULL | 团队类目 |
| invite_code | VARCHAR(10) | UNIQUE, NOT NULL | 6位邀请码 |
| owner_id | UUID | FK→users.id, NOT NULL | 团队拥有者 |
| pool_balance | INTEGER | DEFAULT 0, CHECK >= 0 | 团队池灵感币余额 |
| created_at | TIMESTAMP | DEFAULT NOW() | 创建时间 |

#### team_members 表

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | UUID | PK, NOT NULL | 记录ID |
| user_id | UUID | FK→users.id, NOT NULL | 用户ID |
| team_id | UUID | FK→teams.id, NOT NULL | 团队ID |
| role | ENUM('Owner','Member') | NOT NULL | 团队角色 |
| joined_at | TIMESTAMP | DEFAULT NOW() | 加入时间 |
| **UNIQUE(user_id, team_id)** | | | 联合唯一索引 |

#### generation_batches 表（历史批次）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | UUID | PK, NOT NULL | 批次ID |
| user_id | UUID | FK→users.id, NOT NULL | 提交用户 |
| mode | ENUM('smart','pro') | NOT NULL | 生成模式 |
| status | ENUM('processing','success','partial','failed') | DEFAULT 'processing' | 批次状态 |
| config | JSONB | NOT NULL | 生成配置快照 |
| input_images | JSONB | NOT NULL | 输入图片URL列表 |
| total_count | INTEGER | NOT NULL | 总生成数 |
| success_count | INTEGER | DEFAULT 0 | 成功数 |
| wallet_type | ENUM('personal','team') | NOT NULL | 扣费来源 |
| team_id | UUID | FK→teams.id, NULLABLE | 团队ID（团队扣费时）|
| points_cost | INTEGER | NOT NULL | 本次消耗灵感币 |
| created_at | TIMESTAMP | DEFAULT NOW() | 创建时间 |
| completed_at | TIMESTAMP | NULLABLE | 完成时间 |

#### generated_images 表

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | UUID | PK, NOT NULL | 图片ID |
| batch_id | UUID | FK→generation_batches.id, NOT NULL | 所属批次 |
| task_index | INTEGER | NOT NULL | 在批次中的序号 |
| url | VARCHAR(500) | NULLABLE | OSS图片URL |
| status | ENUM('processing','success','failed') | DEFAULT 'processing' | 生成状态 |
| error_msg | TEXT | NULLABLE | 失败原因 |
| favorited | BOOLEAN | DEFAULT false | 是否已收藏 |
| created_at | TIMESTAMP | DEFAULT NOW() | 创建时间 |
| completed_at | TIMESTAMP | NULLABLE | 完成时间 |

#### favorites 表

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | UUID | PK, NOT NULL | 收藏ID |
| user_id | UUID | FK→users.id, NOT NULL | 收藏用户 |
| image_url | VARCHAR(500) | NOT NULL | 图片URL |
| batch_id | UUID | FK→generation_batches.id, NULLABLE | 来源批次 |
| config | JSONB | NULLABLE | 生成配置快照 |
| created_at | TIMESTAMP | DEFAULT NOW() | 收藏时间 |
| **UNIQUE(user_id, image_url)** | | | 联合唯一（防止重复收藏）|

#### points_records 表（灵感币流水）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | UUID | PK, NOT NULL | 流水ID |
| user_id | UUID | FK→users.id, NOT NULL | 用户 |
| amount | INTEGER | NOT NULL | 正数为入账，负数为出账 |
| type | ENUM('consume','refund','bonus','topup') | NOT NULL | 流水类型 |
| source_wallet | ENUM('personal','team') | NOT NULL | 来源钱包 |
| team_id | UUID | FK→teams.id, NULLABLE | 关联团队 |
| related_batch_id | UUID | FK→generation_batches.id, NULLABLE | 关联批次 |
| description | VARCHAR(255) | NOT NULL | 备注 |
| created_at | TIMESTAMP | DEFAULT NOW() | 创建时间 |

#### pricing_plans 表

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | UUID | PK, NOT NULL | 方案ID |
| name | VARCHAR(100) | NOT NULL | 方案名称 |
| price | DECIMAL(10,2) | NOT NULL, CHECK > 0 | 价格(元) |
| coins | INTEGER | NOT NULL, CHECK > 0 | 基础灵感币数量 |
| bonus_coins | INTEGER | DEFAULT 0 | 赠送灵感币 |
| is_active | BOOLEAN | DEFAULT true | 是否上架 |
| sort_order | INTEGER | DEFAULT 0 | 排序权重 |
| created_at | TIMESTAMP | DEFAULT NOW() | 创建时间 |

#### redemption_codes 表

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | UUID | PK, NOT NULL | 记录ID |
| code | VARCHAR(20) | UNIQUE, NOT NULL | 兑换码 |
| coins | INTEGER | NOT NULL, CHECK > 0 | 面额 |
| expires_at | TIMESTAMP | NOT NULL | 过期时间 |
| is_used | BOOLEAN | DEFAULT false | 是否已使用 |
| used_by | UUID | FK→users.id, NULLABLE | 使用者 |
| used_at | TIMESTAMP | NULLABLE | 使用时间 |
| remark | VARCHAR(255) | NULLABLE | 备注 |
| created_at | TIMESTAMP | DEFAULT NOW() | 创建时间 |

#### announcements 表

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | UUID | PK, NOT NULL | 公告ID |
| title | VARCHAR(200) | NOT NULL | 标题 |
| content | TEXT | NOT NULL | 内容 |
| type | ENUM('info','warning','success','important') | DEFAULT 'info' | 公告类型 |
| is_pinned | BOOLEAN | DEFAULT false | 是否置顶 |
| is_active | BOOLEAN | DEFAULT true | 是否生效 |
| created_by | UUID | FK→users.id, NULLABLE | 创建者(管理员) |
| expires_at | TIMESTAMP | NULLABLE | 过期时间(NULL表示永不过期) |
| created_at | TIMESTAMP | DEFAULT NOW() | 创建时间 |
| updated_at | TIMESTAMP | DEFAULT NOW() | 更新时间 |

### 4.3 枚举值定义

#### SceneStyle（场景风格）— 9种预设

| 值 | 名称 | promptSuffix示例 |
|----|------|-------------------|
| nordic-minimal | 北欧极简 | clean minimalist nordic style, white background |
| amazon-white | 亚马逊白底 | professional white background product photography |
| lifestyle-natural | 生活化自然 | natural lifestyle setting, warm lighting |
| luxury-premium | 奢华高端 | luxury premium feel, dark elegant background |
| seasonal-festive | 节日氛围 | festive holiday atmosphere, seasonal decorations |
| flat-lay | 平铺俯拍 | flat lay composition, top-down view |
| editorial-fashion | 杂志时尚 | editorial fashion magazine style |
| social-media | 社媒爆款 | social media optimized, eye-catching colors |
| tech-digital | 科技数码 | tech product, digital aesthetic, gradient background |

#### LightingStyle（光影风格）— 4种

| 值 | 名称 |
|----|------|
| natural | 自然光 |
| studio-soft | 影棚柔光 |
| warm-dusk | 温暖黄昏 |
| cool-tech | 冷调科技 |

#### CameraAngle（拍摄角度）— 3种

| 值 | 名称 |
|----|------|
| eye-level | 平视 |
| top-down | 俯拍 |
| low-45 | 低角度45° |

#### AspectRatio（图片比例）— 5种

| 值 | 用途 |
|----|------|
| 1:1 | 主图/头像 |
| 3:4 | 竖版详情 |
| 4:3 | 横版详情 |
| 16:9 | Banner/海报 |
| custom | 自定义 |

#### WalletType（钱包类型）

| 值 | 说明 |
|----|------|
| personal | 个人钱包（个人账户余额）|
| team | 团队钱包（团队公共池）|

#### PointsRecordType（流水类型）

| 值 | 说明 | amount符号 |
|----|------|-----------|
| consume | 生成消耗 | 负数 |
| refund | 失败退款 | 正数 |
| bonus | 赠送/奖励 | 正数 |
| topup | 充值购买 | 正数 |

---

## 5. 业务逻辑要点

### 5.1 灵感币计费算法

**核心公式（前端 `utils.ts` 中已实现）：**

```
总费用 = (基础单价 + 参考图附加费) × 商品图片数量

其中:
  基础单价 = 5 灵感币/张
  参考图附加费 = 有参考图 ? 2 : 0 灵感币/张

示例:
  - 3张商品图，无参考图 = (5 + 0) × 3 = 15 灵感币
  - 5张商品图，有参考图 = (5 + 2) × 5 = 35 灵感币
```

**各功能模块独立定价：**

| 功能 | 单价 | 说明 |
|------|------|------|
| AI商品图(Smart/Pro) | (5 + refCost) × count | 见上方公式 |
| AI营销海报 | 8 灵感币/张 | 固定价格 |
| AI视频短片 | 15 灵感币/条 | 固定价格 |
| AI增强 | 5 灵感币/次 | 工具箱 |
| 去水印 | 3 灵感币/次 | 工具箱 |
| 消除物体 | 4 灵感币/次 | 工具箱 |

### 5.2 双钱包扣费流程

```
用户点击[生成]
     │
     ▼
┌─────────────────────┐
│ 1. 前端计算预估费用  │ ← calculateCost(productCount, hasReference)
└──────────┬──────────┘
           │
           ▼
┌─────────────────────────────┐
│ 2. 前端检查余额是否充足       │ ← selectedWalletBalance >= estimatedCost
│    不足则显示警告 + 跳转充值  │
└──────────┬──────────────────┘
           │ 充足
           ▼
┌─────────────────────────────┐
│ 3. 后端接收生成请求           │
│    • 二次校验余额             │
│    • 预扣费（事务操作）        │
│    • 写入 points_records      │  type='consume', amount=-cost
│    • 更新钱包余额              │
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│ 4. 创建批次 & 投入队列        │
│    generation_batches INSERT │  status='processing'
│    generated_images INSERT   │  status='processing'
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│ 5. 异步生成（消息队列消费者）  │
│    • 调用AI模型API           │
│    • 成功 → 更新图片状态      │  status='success', url=oss_url
│    • 失败 → 更新图片状态      │  status='failed', error_msg=...
└──────────┬──────────────────┘
           │ 全部完成
           ▼
┌─────────────────────────────┐
│ 6. 批次结算                  │
│    • 更新批次状态              │  success/partial/failed
│    • 如有失败图片 → 自动退款    │  points_records: type='refund'
│    • 退还对应钱包余额           │
└─────────────────────────────┘
```

**关键约束：**
- 预扣费和创建批次必须在同一数据库事务中完成
- 退款操作必须是幂等的（防止重复退款）
- 团队钱包扣费时需校验用户是否为该团队成员

### 5.3 异步图像生成架构

**推荐架构：**

```
┌──────────┐    HTTP     ┌──────────┐    MQ Push    ┌──────────────┐
│  前端应用  │ ────────►  │  API服务  │ ──────────►  │  Redis/RabbitMQ│
│          │            │ (Fast/Go) │              │   Task Queue  │
└──────────┘            └──────────┘              └──────┬───────┘
       ▲                                                │
       │ SSE/Polling                                     │ Consume
       │                                                ▼
       │                                   ┌──────────────────────┐
       │                                   │   Worker 进程         │
       │                                   │  ┌─────────────────┐ │
       │                                   │  │ AI Model Adapter │ │
       │                                   │  │ (Qwen/GPT-Image) │ │
       │                                   │  └────────┬────────┘ │
       │                                   └──────────┼──────────┘
       │                                              │
       │                                   ┌──────────▼──────────┐
       │                                   │   结果回写 DB + OSS   │
       │                                   │   + SSE Event 推送   │
       └───────────────────────────────────┴─────────────────────┘
```

**关键技术决策点：**

| 决策项 | 推荐方案 | 备选方案 |
|--------|----------|----------|
| 进度推送 | SSE (Server-Sent Events) | WebSocket | 轮询(Polling) |
| 任务队列 | Redis Stream / BullMQ | RabbitMQ | Kafka |
| 并发控制 | 每用户最多3个并发任务 | 令牌桶限流 |
| 超时处理 | 单张超时120s → 标记失败并退款 | 可配置 |
| 重试策略 | 失败自动重试1次 | 指数退避 |

### 5.4 图片上传与OSS存储

**上传流程：**

```
前端选择文件
    │
    ▼
前端校验（格式/大小/数量）
    │
    ▼
POST /api/v1/upload/image (multipart/form-data)
    │
    ▼
后端二次校验
    │
    ├── 安全扫描（可选：阿里云内容安全/自建模型）
    ├── 生成唯一存储路径: /uploads/{year}/{month}/{uuid}.{ext}
    ├── 上传至 OSS / MinIO
    ├── 返回可访问 URL
    └── 记录文件元信息到 files 表（可选）
```

**存储路径规划：**

```
bucket/
├── uploads/
│   └── {year}/{month}/
│       ├── product/          # 商品图
│       │   └── {uuid}.jpg
│       └── reference/        # 参考图
│           └── {uuid}.png
├── generated/
│   └── {year}/{month}/{day}/
│       └── {batch_id}/
│           ├── {image_uuid}_001.jpg
│           └── {image_uuid}_002.jpg
└── avatars/                  # 用户头像
    └── {user_id}.jpg
```

**文件约束（前后端必须一致）：**

| 约束项 | 值 |
|--------|-----|
| 允许格式 | JPEG, PNG, WebP |
| 单文件大小 | ≤ 10 MB |
| 商品图数量上限 | 10 张/批次 |
| 参考图数量 | 1 张 |
| URL有效期 | 永久有效（私有桶需签名URL，有效期1小时）|

### 5.5 图片尺寸约束规则（关键！）

**前端 `utils.ts` 中实现的约束，后端必须完全复用：**

```typescript
// 尺寸限制常量
const SIZE_LIMITS = {
  MAX_SIDE: 3840,        // 最大边长不超过3840px
  MULTIPLE_OF: 16,       // 宽高必须为16的倍数
  MAX_RATIO: 3,          // 宽高比不超过3:1
  MIN_PIXELS: 655360,    // 总像素最小值 ≈ 808x811
  MAX_PIXELS: 8294400,   // 总像素最大值 ≈ 2880x2880
}
```

**校验与修正算法（后端需实现相同逻辑）：**

```
输入: width, height

1. 向下取整到16的倍数:
   width = floor(width / 16) * 16
   height = floor(height / 16) * 16

2. 限制最大边长:
   if width > 3840: width = 3840
   if height > 3840: height = 3840

3. 限制宽高比 (max 3:1):
   ratio = max(width, height) / min(width, height)
   if ratio > 3:
     if width > height: height = ceil(width / 3 / 16) * 16
     else: width = ceil(height / 3 / 16) * 16

4. 限制像素范围:
   totalPixels = width * height
   if totalPixels < 655360:
     scale = sqrt(655360 / totalPixels)
     width = round(width * scale / 16) * 16
     height = round(height * scale / 16) * 16
   if totalPixels > 8294400:
     scale = sqrt(8294400 / totalPixels)
     width = round(width * scale / 16) * 16
     height = round(height * scale / 16) * 16

输出: corrected_width, corrected_height
```

**分辨率预设映射：**

| 预设值 | 基准像素 | 说明 |
|--------|----------|------|
| 1K | 1024 | 入门质量 |
| 2K | 2048 | 标准质量（推荐）|
| 4K | 4096 | 高清质量 |

**根据比例和分辨率预算计算最终尺寸（`resolveSizeFromRatioAndResolution`）：**

```
输入: ratioStr ("16:9"), resolutionBudget (2048)

1. 解析比例: w_ratio = 16, h_ratio = 9
2. 计算基准尺寸:
   if w_ratio >= h_ratio:
     base_width = resolutionBudget
     base_height = resolutionBudget * h_ratio / w_ratio
   else:
     base_height = resolutionBudget
     base_width = resolutionBudget * w_ratio / h_ratio
3. 应用 SIZE_LIMITS 约束修正
4. 返回最终 { width, height }

例: ratio="16:9", budget=2048 → { width: 2048, height: 1152 }
   ratio="1:1", budget=2048  → { width: 2048, height: 2048 }
   ratio="3:4", budget=2048  → { width: 1536, height: 2048 }
```

### 5.6 AI对话功能（Pro Mode 分析整合）

**此功能需要后端集成 LLM 服务，是前后端交互最复杂的环节之一。**

**对话流程：**

```
用户点击[分析整合]
     │
     ▼
前端收集所有 taskCards 配置
     │
     ▼
POST /api/v1/generate/pro/analyze
  Request: { taskCards: [...], conversationHistory: [] }
     │
     ▼
后端构建 System Prompt:
  "你是EcomAI Studio的专业AI视觉顾问...
   请分析以下电商图像生成任务配置并给出优化建议..."
     │
     ▼
拼接 User Message (JSON格式的配置摘要)
     │
     ▼
调用 LLM API (OpenAI / 通义千问)
     │
     ▼
解析 LLM 返回的结构化数据
     │
     ▼
返回 { overview, suggestions[], reply, optimizedConfigs? }
     │
     ▼
前端渲染对话界面 + 建议卡片
     │
     ▼
用户继续对话（可选）
  → 再次 POST /api/v1/generate/pro/analyze
    Request: { taskCards: [...], conversationHistory: [msg1, msg2, assistantReply] }
    → LLM 基于完整对话上下文回复
```

**System Prompt 设计建议：**
```
你是一位专业的跨境电商AI视觉顾问，服务于EcomAI Studio平台。
你的职责是分析用户的AI图像生成任务配置，提供专业优化建议。

分析维度：
1. 场景风格与产品的匹配度
2. 光影效果选择的合理性
3. 构图角度对产品展示的影响
4. 提示词的有效性和完整性
5. 多任务之间的协调性

输出要求：
- 先给出整体概览（2-3句话总结）
- 逐条列出具体建议（带优先级）
- 最后给出一段自然的对话式总结
- 如果用户提出了具体问题，针对性回答
```

### 5.7 兑换码一次性使用 + 过期校验

```
用户输入兑换码
     │
     ▼
POST /api/v1/purchase/redeem
     │
     ▼
查询 redemption_codes WHERE code = ?
     │
     ├── 不存在 → 返回 4001 "兑换码不存在"
     ├── is_used = true → 返回 4002 "兑换码已被使用"
     ├── expires_at < NOW() → 返回 4003 "兑换码已过期"
     │
     ▼
校验通过
     │
     ▼
BEGIN TRANSACTION
  ├── UPDATE redemption_codes SET is_used=true, used_by=?, used_at=NOW()
  ├── UPDATE users SET personal_points = personal_points + ?  (或 team.pool_balance)
  ├── INSERT INTO points_records (amount=+, type='bonus', ...)
COMMIT
     │
     ▼
返回 { coinsAdded, newBalance }
```

---

## 6. 认证与安全

### 6.1 JWT Token 设计

**Token Payload 结构：**

```json
{
  "sub": "user-uuid",        // Subject: 用户ID
  "email": "user@example.com",
  "role": "user",            // user | admin
  "iat": 1749000000,         // Issued At: 签发时间
  "exp": 1749086400          // Expiration: 过期时间（默认24小时）
}
```

**Token 签发与刷新：**

| 操作 | 说明 |
|------|------|
| 登录签发 | 登录成功后签发 Access Token（24h有效）+ Refresh Token（7天有效）|
| Refresh Token | 用于刷新 Access Token，存储在 HttpOnly Cookie 中 |
| Token黑名单 | 退出登录时将Token加入Redis黑名单（TTL = 剩余过期时间）|

### 6.2 角色权限矩阵

| 资源/操作 | user（普通用户）| admin（管理员）|
|-----------|-----------------|---------------|
| 登录/注册/登出 | ✅ | ✅ |
| 查看个人信息 | ✅（仅自己的）| ✅ |
| AI图像生成 | ✅ | ✅ |
| 查看/克隆自己历史 | ✅ | ✅ |
| 收藏管理 | ✅（仅自己的）| ✅ |
| 团队（创建/加入/管理）| ✅ | ✅ |
| 充值/兑换码使用 | ✅ | ✅ |
| 管理后台全部功能 | ❌ | ✅ |
| 定价方案管理 | ❌ | ✅ |
| 兑换码生成 | ❌ | ✅ |
| 公告发布 | ❌ | ✅ |
| 查看全站数据统计 | ❌ | ✅ |

**后端权限校验中间件伪代码：**

```typescript
function requireAuth(req, res, next) {
  const token = req.headers.authorization?.replace('Bearer ', '')
  if (!token) return res.status(401).json({ code: 1001, message: '未登录' })

  try {
    const payload = verifyJWT(token)
    req.user = payload
    next()
  } catch (e) {
    return res.status(401).json({ code: 1002, message: 'Token无效或已过期' })
  }
}

function requireAdmin(req, res, next) {
  requireAuth(req, res, () => {
    if (req.user.role !== 'admin') {
      return res.status(403).json({ code: 1003, message: '无权限访问' })
    }
    next()
  })
}
```

### 6.3 验证码防刷机制

| 防护措施 | 实现 |
|----------|------|
| 频率限制 | 同一IP 60秒内最多1次请求 |
| 每日限额 | 同一邮箱每天最多10条验证码 |
| 验证码有效期 | 5分钟内有效 |
| 验证码格式 | 6位纯数字 |
| 发送渠道 | SMTP邮件服务（如阿里云邮件推送/SendGrid）|

**Redis 数据结构设计（频率限制）：**

```
# IP级别频率限制
SET email:rate:{ip} 1 EX 60 NX

# 邮箱每日限额
INCR email:daily:{email}
EXPIRE email:daily:{email} 86400
# > 10 则拒绝
```

### 6.4 敏感操作二次确认

以下操作建议前端弹出确认框，后端也做日志记录：

| 操作 | 确认要求 |
|------|----------|
| 删除历史批次 | 确认"删除后不可恢复" |
| 移除团队成员 | 确认"移除后成员将失去团队资源访问权" |
| 删除定价方案 | 确认"正在使用的方案不可删除" |
| 支付下单 | 确认金额和套餐内容 |
| 大额充值 | 超过500元需二次确认 |

---

## 7. 错误处理规范

### 7.1 统一错误码体系

| 错误码范围 | 分类 | 说明 |
|------------|------|------|
| 0 | 成功 | 业务处理成功 |
| 1xxx | 认证授权错误 | Token相关 |
| 2xxx | 业务逻辑错误 | 余额不足/参数不合法等 |
| 3xxx | 参数校验错误 | 请求参数不符合要求 |
| 4xxx | 第三方服务错误 | AI模型/OSS/支付网关异常 |
| 5xxx | 系统内部错误 | 服务器未知异常 |

### 7.2 详细错误码清单

#### 1xxx — 认证授权

| 错误码 | HTTP状态码 | message | 说明 |
|--------|-----------|---------|------|
| 1001 | 401 | 未登录 | 请求未携带有效Token |
| 1002 | 401 | Token无效或已过期 | JWT解析失败或已过期 |
| 1003 | 403 | 无权限访问 | 角色权限不足 |
| 1004 | 401 | Token已注销 | Token在黑名单中 |
| 1005 | 401 | 登录态已失效 | Session/Cookie过期 |

#### 2xxx — 业务逻辑

| 错误码 | HTTP状态码 | message | 说明 |
|--------|-----------|---------|------|
| 2001 | 400 | 余额不足 | 钱包灵感币不够支付 |
| 2002 | 403 | 不属于该团队 | 用户非目标团队成员 |
| 2003 | 403 | 非团队Owner | 需要Owner权限的操作 |
| 2004 | 400 | 团队人数已达上限 | 团队成员数量超限 |
| 2005 | 400 | 邀请码无效 | 6位邀请码不存在或已禁用 |
| 2006 | 409 | 已是该团队成员 | 重复加入 |
| 2007 | 400 | 批次正在进行中 | 不可删除正在处理的批次 |
| 2008 | 400 | 商品图片数量超限 | 超过10张限制 |
| 2009 | 400 | 生成任务并发数超限 | 每用户最多3个并发任务 |

#### 3xxx — 参数校验

| 错误码 | HTTP状态码 | message | 说明 |
|--------|-----------|---------|------|
| 3001 | 400 | 参数缺失 | 必填字段未提供 |
| 3002 | 400 | 参数格式错误 | 字段类型/格式不符 |
| 3003 | 400 | 图片尺寸不合规 | 未满足SIZE_LIMITS约束 |
| 3004 | 400 | 文件格式不支持 | 非JPG/PNG/WebP |
| 3005 | 413 | 文件大小超限 | 超过10MB |
| 3006 | 400 | 枚举值无效 | 传入了不在允许范围内的枚举值 |
| 3007 | 400 | 验证码错误 | 输入的验证码不正确 |
| 3008 | 429 | 操作过于频繁 | 触发频率限制 |

#### 4xxx — 第三方服务

| 错误码 | HTTP状态码 | message | 说明 |
|--------|-----------|---------|------|
| 4001 | 404 | 兑换码不存在 | 输入的兑换码未找到 |
| 4002 | 409 | 兑换码已被使用 | 一次性兑换码不可重复使用 |
| 4003 | 400 | 兑换码已过期 | 超过了过期时间 |
| 4004 | 502 | AI模型服务异常 | 通义千问/GPT API调用失败 |
| 4005 | 502 | AI模型超时 | 单次生成超过120秒 |
| 4006 | 502 | 图片内容审核不通过 | 包含违规内容 |
| 4007 | 502 | OSS上传失败 | 对象存储服务异常 |
| 4008 | 502 | 支付网关异常 | 支付回调处理失败 |

#### 5xxx — 系统内部

| 错误码 | HTTP状态码 | message | 说明 |
|--------|-----------|---------|------|
| 5001 | 500 | 服务器内部错误 | 未预期的异常 |
| 5002 | 503 | 服务暂不可用 | 维护中/过载 |
| 5003 | 500 | 数据库操作失败 | SQL执行异常 |
| 5004 | 500 | 缓存服务异常 | Redis连接失败 |

### 7.3 特殊错误场景处理

**余额不足时的完整交互：**
```
前端 canGenerate 校验 → balance < cost
  → 显示警告横幅："余额不足，还需 XX 灵感币"
  → 提供 [去充值] 按钮（跳转 /purchase）
  → 若用户强行发起请求 → 后端返回 2001 错误
  → 前端拦截错误码 → 弹出充值引导弹窗
```

**AI生成部分失败的处理：**
```
批次共5张图片 → 3张成功，2张失败
  → 批次状态标记为 partial
  → 自动退还2张失败图的费用（type='refund'）
  → 前端展示：3张正常图 + 2张失败图（带重试按钮）
  → 用户可点击重试 → 仅对失败图重新扣费生成
```

**并发冲突处理（钱包余额）：**
```
用户快速连续点击两次生成
  → 使用数据库行锁 (SELECT FOR UPDATE)
  → 或乐观锁 (WHERE balance = expected_balance)
  → 第二次请求检测到余额不足 → 返回 2001
```

---

## 8. 后端技术选型建议

### 8.1 推荐技术栈组合

| 层次 | 推荐选项 | 替代方案 | 选型理由 |
|------|----------|----------|----------|
| **运行时** | Node.js 20+ (Fastify/NestJS) | Go (Gin/Fiber) | 与前端TS生态统一，开发效率高 |
| **数据库** | PostgreSQL 16 | MySQL 8.0 | JSONB支持好，适合config字段 |
| **缓存** | Redis 7 | Memcached | 必选：Session/Rate Limiting/Queue |
| **ORM** | Prisma / Drizzle ORM | TypeORM | 类型安全，迁移友好 |
| **消息队列** | Redis BullMQ | RabbitMQ | 轻量，与Redis共用 |
| **对象存储** | 阿里云 OSS | MinIO / AWS S3 | 国内访问速度快 |
| **AI图像模型** | 通义千问VL (qwen-vl-max) | GPT-Image-2 / Midjourney API | 双模型备份策略 |
| **AI对话LLM** | OpenAI GPT-4o-mini | 通义千问-turbo | Pro Mode分析整合 |
| **支付网关** | 支付宝/微信支付 | Stripe | 国内用户为主 |
| **邮件服务** | 阿里云邮件推送 | SendGrid / Resend | 验证码发送 |
| **内容安全** | 阿里云内容安全 | 自建模型 | 图片/文本违规检测 |
| **监控** | Prometheus + Grafana | Datadog | 仪表盘数据源 |

### 8.2 项目目录结构建议

```
backend/
├── src/
│   ├── index.ts                 # 入口文件
│   ├── config/                  # 配置管理
│   │   ├── database.ts
│   │   ├── redis.ts
│   │   ├── oss.ts
│   │   └── ai-services.ts
│   ├── modules/                 # 按业务模块划分
│   │   ├── auth/                # 认证模块
│   │   │   ├── auth.controller.ts
│   │   │   ├── auth.service.ts
│   │   │   ├── auth.routes.ts
│   │   │   └── jwt.strategy.ts
│   │   ├── user/                # 用户模块
│   │   ├── generate/            # 生成模块（核心）
│   │   │   ├── generate.controller.ts
│   │   │   ├── generate.service.ts
│   │   │   ├── task.queue.ts    # 任务队列
│   │   │   ├── ai-adapter/      # AI模型适配器
│   │   │   │   ├── qwen.adapter.ts
│   │   │   │   └── gpt.adapter.ts
│   │   │   └── sse.service.ts   # SSE推送
│   │   ├── upload/              # 文件上传模块
│   │   ├── history/             # 历史记录模块
│   │   ├── favorite/            # 收藏模块
│   │   ├── team/                # 团队模块
│   │   ├── purchase/            # 支付充值模块
│   │   ├── poster/              # 海报生成模块
│   │   ├── video/              # 视频生成模块
│   │   ├── toolbox/            # 工具箱模块
│   │   └── admin/              # 管理后台模块
│   │       ├── stats.controller.ts
│   │       ├── pricing.controller.ts
│   │       ├── consumption.controller.ts
│   │       ├── redemption.controller.ts
│   │       └── announcement.controller.ts
│   ├── common/                 # 公共模块
│   │   ├── errors/             # 错误类定义
│   │   ├── interceptors/       # 拦截器（响应格式化/日志）
│   │   ├── guards/             # 守卫（认证/角色）
│   │   ├── decorators/         # 自定义装饰器
│   │   ├── validators/         # DTO校验（class-validator）
│   │   └── utils/              # 工具函数（尺寸校验/成本计算）
│   └── entities/               # 数据库实体定义（Prisma Schema）
├── prisma/
│   └── schema.prisma           # 数据库模型定义
├── tests/
│   ├── unit/
│   └── integration/
└── package.json
```

### 8.3 关键非功能性需求

| 需求 | 指标 | 说明 |
|------|------|------|
| **API响应时间** | P95 < 500ms | 非生成类接口 |
| **生成等待时间** | 单张 < 30s | AI模型调用+传输 |
| **并发用户** | 支持 500 DAU | 初期规模 |
| **并发生成任务** | 每用户 ≤ 3 | 队列限流 |
| **可用性** | 99.5% SLA | 核心服务 |
| **数据持久性** | 99.999% | OSS多副本 |
| **图片保留期** | 90天 | 生成结果保留期限 |

---

## 9. Mock数据迁移对照表

> 前端当前使用 `src/mock/data.ts` 模拟所有API数据。以下是Mock数据与后端API的对应关系，方便逐步替换。

### Mock变量 → API接口对照

| Mock变量 | 类型 | 对应API | HTTP方法 |
|----------|------|---------|----------|
| `mockUser` / `mockAdmin` | User | `/api/v1/auth/me` 或 `/api/v1/auth/login` | GET / POST |
| `mockTeams` | Team[] | `/api/v1/teams` | GET |
| `mockPointsRecords` | PointsRecord[] | `/api/v1/user/points-records` | GET |
| `mockStyleCards` | StyleCard[] | `/api/v1/styles` | GET |
| `mockFeatureCards` | FeatureCard[] | `/api/v1/features` | GET |
| `mockInspirations` | InspirationItem[] | `/api/v1/inspirations` | GET |
| `mockHistory` | HistoryBatch[] | `/api/v1/history` | GET |
| `mockFavorites` | FavoriteItem[] | `/api/v1/favorites` | GET |
| `mockAdminStats` | AdminStats | `/api/v1/admin/stats/dashboard` | GET |
| `mockPricingPlans` | PricingPlan[] | `/api/v1/pricing-plans` 或 `/api/v1/admin/pricing-plans` | GET |
| `mockTeamConsumptions` | TeamConsumption[] | `/api/v1/admin/consumptions` | GET |
| `mockRedemptionCodes` | RedemptionCode[] | `/api/v1/admin/redemption-codes` | GET |
| `mockAnnouncements` | Announcement[] | `/api/v1/announcements/public` 或 `/api/v1/admin/announcements` | GET |
| `hotTags` | string[] | `/api/v1/inspirations/tags` | GET |

### 前端需改造的关键函数

| 函数位置 | 当前行为 | 需改为 |
|----------|----------|--------|
| `auth.ts` → `login()` | 设置localStorage + 加载mockUser | 调用 `POST /api/v1/auth/login`，存储JWT |
| `auth.ts` → `register()` | 直接设置loggedIn | 调用 `POST /api/v1/auth/register` |
| `auth.ts` → `logout()` | 清除localStorage | 调用 `POST /api/v1/auth/logout` + 清Token |
| `auth.ts` → `deductPoints()` | 本地减少points数值 | 调用后端接口（随generate请求一并处理）|
| `auth.ts` → `topupPersonal()` | 本地增加points | 调用 `POST /api/v1/purchase/pay-confirm` 回调 |
| `workspace.ts` → `simulateGeneration()` | setTimeout模拟延迟+随机成功 | 调用 `POST /api/v1/generate` + 监听SSE |
| `AssetPanel.vue` → 上传处理 | 本地URL.createObjectURL | 调用 `POST /api/v1/upload/image` 获取OSS URL |
| `HomeView.vue` → "复制同款" | 本地加载mock配置 | 调用 `POST /api/v1/history/:batchId/clone` |
| `PurchaseView.vue` → 兑换码 | 本地增加余额 | 调用 `POST /api/v1/purchase/redeem` |
| `ProMode.vue` → AI分析 | 无实际调用 | 调用 `POST /api/v1/generate/pro/analyze` |
| `ToolboxView.vue` → AI工具 | 无实际调用 | 调用 `POST /api/v1/toolbox/process` |
| `PosterView.vue` → 生成 | 无实际调用 | 调用 `POST /api/v1/poster/generate` |
| `VideoView.vue` → 生成 | 无实际调用 | 调用 `POST /api/v1/video/generate` |

### 推荐迁移顺序

建议按以下优先级逐步替换Mock数据为真实API调用：

```
第一阶段（核心链路打通）:
  1. 认证接口（login/register/send-code/logout/me）
  2. 文件上传接口（upload/image）
  3. 核心生成接口（generate + SSE状态推送）
  4. 用户资产接口（balance/points-records）

第二阶段（完善功能）:
  5. 历史记录接口（history CRUD）
  6. 收藏接口（favorites CRUD）
  7. 团队接口（teams/members/join）
  8. 支付充值接口（pricing-plans/create-order/redeem）

第三阶段（扩展功能）:
  9. Pro Mode AI分析接口（pro/analyze）
  10. 内容生成接口（poster/video/toolbox）
  11. 管理后台接口（admin/*）
  12. 公共接口（styles/inspirations/announcements/features）
```

---

## 附录

### A. 前端Store状态结构速查

**useAppStore:**
```typescript
{ sidebarCollapsed: boolean, sidebarExpanded: boolean }
```

**useAuthStore:**
```typescript
{
  user: User | null,
  isAdmin: computed,
  isLoggedIn: computed,
  teams: Team[],
  currentTeamId: string | null,
  selectedWallet: WalletType,
  pointsRecords: PointsRecord[],
  // computed
  currentTeam: Team | undefined,
  teamPoolBalance: number,
  selectedWalletBalance: number,
  // methods
  login(email, code),
  register(),
  logout(),
  switchTeam(teamId),
  switchWallet(wallet),
  deductPoints(amount): boolean,
  topupPersonal(amount, desc),
  topupTeam(teamId, amount, desc)
}
```

**useWorkspaceStore:**
```typescript
{
  mode: GenerationMode,
  productImages: ProductImage[],      // 最多10张
  referenceImage: ReferenceImage | null,
  sceneStyle: SceneStyle | null,
  proConfig: ProConfig,
  generatedImages: GeneratedImage[],
  isGenerating: boolean,
  batchId: string | null,
  // computed
  estimatedCost: number,              // calculateCost()
  canGenerate: boolean,
  currentConfig: GenerationConfig,
  // methods
  setMode(mode),
  addProductImages(files),            // 限制10张
  removeProductImage(id),
  setReferenceImage(file),
  updateReferenceStrength(strength),
  setSceneStyle(style),
  updateProConfig(config),
  simulateGeneration(),               // ⚠️ 需替换为API调用
  reset(),
  loadConfig(config)
}
```

### B. 前端HTTP客户端配置建议

前端当前无axios/fetch封装层。建议新增 `src/api/client.ts`：

```typescript
// 建议的HTTP客户端基础配置
const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api/v1',
  timeout: 30000,                    // 生成接口可能较慢
  headers: { 'Content-Type': 'application/json' }
})

// 请求拦截器 — 注入Token
apiClient.interceptors.request.use(config => {
  const token = localStorage.getItem('ecomai_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// 响应拦截器 — 统一错误处理
apiClient.interceptors.response.use(
  response => response.data,
  error => {
    const { code, message } = error.response?.data || {}
    // 1001/1002 → 跳转登录
    if ([1001, 1002].includes(code)) {
      router.push('/login')
    }
    // 2001 → 余额不足提示
    if (code === 2001) {
      showBalanceWarning()
    }
    return Promise.reject(error)
  }
)
```

### C. 环境变量清单

| 变量名 | 说明 | 示例值 |
|--------|------|--------|
| `VITE_API_BASE_URL` | 后端API地址 | `http://localhost:3000/api/v1` |
| `VITE_OSS_BUCKET` | OSS Bucket名称 | `ecomai-studio-assets` |
| `VITE_OSS_REGION` | OSS区域 | `oss-cn-hangzhou` |
| `VITE_APP_NAME` | 应用名称 | `EcomAI Studio` |
| `VITE_WS_URL` | WebSocket地址（如使用）| `ws://localhost:3000/ws` |

---

> **文档结束**
>
> 本文档基于前端源码全面分析生成，涵盖了后端开发所需的全部技术细节。
> 如有任何疑问，请参照前端源码中对应的组件和类型定义进行交叉验证。
