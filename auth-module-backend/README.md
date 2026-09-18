# EcomAI Studio - 认证模块后端

基于 Python Flask 的认证模块后端服务，提供用户注册、登录、验证码发送、密码重置、JWT 鉴权及基于角色的访问控制（RBAC）。

## 环境要求

- Python 3.10+
- MySQL 8.0+
- pip（Python 包管理器）

## 目录结构

```
auth-module-backend/
├── app.py                  # 应用入口（Flask 工厂函数）
├── config.py               # 配置管理（数据库/JWT/邮件/限流/验证码）
├── requirements.txt        # 依赖清单
├── init_db.sql             # 数据库初始化脚本
├── README.md               # 本文件
├── models/
│   ├── user.py             # 用户数据模型（CRUD）
│   └── verification_code.py # 验证码数据模型
├── routes/
│   └── auth.py             # 认证路由注册
├── controllers/
│   └── auth_controller.py  # 认证控制器
├── services/
│   ├── auth_service.py     # 认证业务逻辑
│   ├── email_service.py    # 邮件发送服务
│   └── verification_service.py # 验证码业务服务
├── middleware/
│   └── auth_middleware.py  # JWT 鉴权 + RBAC 中间件
├── utils/
│   └── security.py         # 密码加密 / JWT 令牌 / 限流
└── tests/
    └── test_auth.py        # 单元测试
```

## 快速开始

### 1. 安装依赖

```bash
cd auth-module-backend
pip install -r requirements.txt
```

### 2. 初始化数据库

```bash
# 使用 root 用户登录 MySQL 并执行初始化脚本（按提示输入密码）
mysql -u root -p < init_db.sql
```

初始化脚本会：
- 创建数据库 `ecomai_auth`
- 创建 `users` 表
- 创建 `verification_codes` 表
- 插入两个开发测试账号（密码以 bcrypt 哈希存储，脚本中不含明文）

### 3. 启动服务

```bash
python app.py
```

服务默认运行在 `http://localhost:5000`。

### 4. 运行测试

```bash
# 先创建测试数据库
mysql -u root -p -e "CREATE DATABASE IF NOT EXISTS ecomai_auth_test"

# 修改 init_db.sql 中的数据库名后导入，或手动执行：
# mysql -u root -p ecomai_auth_test < init_db.sql

# 运行测试
python -m pytest tests/ -v
```

## API 接口文档

| 方法 | 路径 | 认证 | 角色 | 说明 |
|------|------|------|------|------|
| POST | `/api/v1/auth/register` | 否 | - | 用户注册 |
| POST | `/api/v1/auth/login` | 否 | - | 密码登录 |
| POST | `/api/v1/auth/login/code` | 否 | - | 验证码登录 |
| POST | `/api/v1/auth/send-code` | 否 | - | 发送验证码 |
| POST | `/api/v1/auth/reset-password` | 否 | - | 重置密码 |
| GET | `/api/v1/auth/me` | 是 | user/admin | 获取当前用户信息 |
| GET | `/api/v1/admin/profile` | 是 | admin | 管理员信息（示例受保护接口）|
| GET | `/api/v1/user/profile` | 是 | user/admin | 用户信息（示例受保护接口）|
| GET | `/api/v1/health` | 否 | - | 健康检查 |

### 统一响应格式

**成功响应：**
```json
{
  "code": 0,
  "message": "success",
  "data": { ... }
}
```

**错误响应：**
```json
{
  "code": 1001,
  "message": "错误描述",
  "data": null
}
```

### 接口详情

#### POST /api/v1/auth/register — 用户注册

**请求体：**
```json
{
  "email": "user@example.com",
  "password": "SecurePass1!",
  "code": "123456"
}
```

**密码要求：** 至少 8 位，包含大写字母、数字、特殊字符（!@#$%^&*(),.?":{}|<>）

**成功响应（201）：**
```json
{
  "code": 0,
  "message": "注册成功",
  "data": {
    "token": "eyJhbGciOi...",
    "user": {
      "id": 1,
      "email": "user@example.com",
      "role": "user"
    }
  }
}
```

**错误码：**
- 2006 (409): 邮箱已被注册
- 3002 (400): 邮箱格式无效 / 密码强度不足 / 验证码不能为空
- 3008 (429): 注册请求过于频繁
- 3009 (400): 验证码无效或已过期

#### POST /api/v1/auth/login — 用户登录

**请求体：**
```json
{
  "email": "user@example.com",
  "password": "YourPassword"
}
```

**成功响应（200）：**
```json
{
  "code": 0,
  "message": "登录成功",
  "data": {
    "token": "eyJhbGciOi...",
    "user": {
      "id": 1,
      "email": "user@example.com",
      "role": "admin"
    }
  }
}
```

**错误码：**
- 1001 (401): 邮箱或密码错误
- 3002 (400): 邮箱或密码不能为空
- 3008 (429): 登录请求过于频繁

#### POST /api/v1/auth/login/code — 验证码登录

**请求体：**
```json
{
  "email": "user@example.com",
  "code": "123456"
}
```

**成功响应（200）：**
```json
{
  "code": 0,
  "message": "登录成功",
  "data": {
    "token": "eyJhbGciOi...",
    "user": {
      "id": 1,
      "email": "user@example.com",
      "role": "user"
    }
  }
}
```

**错误码：**
- 1001 (401): 验证码无效或已过期
- 3002 (400): 邮箱或验证码不能为空
- 3008 (429): 登录请求过于频繁

#### POST /api/v1/auth/send-code — 发送验证码

**请求体：**
```json
{
  "email": "user@example.com",
  "purpose": "login"
}
```

**purpose 可选值：** `login`（登录）、`register`（注册）、`reset_password`（重置密码）

**成功响应（200）：**
```json
{
  "code": 0,
  "message": "验证码已发送",
  "data": {
    "message": "验证码已发送",
    "expires_in": 300
  }
}
```

**约束：** 同一邮箱 60 秒内只能发送 1 次；每日最多 10 次。

**错误码：**
- 3002 (400): 邮箱不能为空 / purpose 参数无效
- 3008 (429): 发送过于频繁 / 超过每日上限

#### POST /api/v1/auth/reset-password — 重置密码

**请求体：**
```json
{
  "email": "user@example.com",
  "code": "123456",
  "password": "NewSecurePass1!"
}
```

**密码要求：** 至少 8 位，包含大写字母、数字、特殊字符（!@#$%^&*(),.?":{}|<>）

**成功响应（200）：**
```json
{
  "code": 0,
  "message": "密码重置成功",
  "data": {
    "message": "密码重置成功"
  }
}
```

**错误码：**
- 1001 (404): 该邮箱未注册
- 3002 (400): 邮箱/验证码/新密码不能为空 / 密码强度不足
- 3008 (429): 操作过于频繁
- 3009 (400): 验证码无效或已过期

#### GET /api/v1/auth/me — 获取当前用户信息

**请求头：** `Authorization: Bearer <token>`

**成功响应（200）：**
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "user": {
      "id": 1,
      "email": "user@example.com",
      "role": "admin",
      "is_active": true,
      "created_at": "2026-01-01T00:00:00",
      "updated_at": "2026-01-01T00:00:00"
    }
  }
}
```

## 开发测试账号

`init_db.sql` 会写入两个**仅供本地开发与自动化测试**的账号：

| 邮箱 | 角色 |
|------|------|
| admin@ecomai.local | admin |
| user@ecomai.local | user |

密码以 bcrypt 哈希存储，`init_db.sql` 与本文档均不记录明文；自动化测试所需的密码定义在 `tests/` 目录中。

> 安全提示：这两个账号是公开可知的默认凭据。**对外部署前必须修改密码或删除**，详见 [docs/SECURITY.md](../docs/SECURITY.md)。

## 错误码汇总

| 错误码 | HTTP状态码 | 说明 |
|--------|-----------|------|
| 0 | 200/201 | 成功 |
| 1001 | 401 | 未登录或凭证无效 |
| 1002 | 401 | Token无效或已过期 |
| 1003 | 403 | 权限不足 |
| 2006 | 409 | 邮箱已被注册 |
| 3002 | 400 | 参数格式错误 |
| 3008 | 429 | 请求过于频繁 |
| 3009 | 400 | 验证码无效或已过期 |
| 5001 | 500/404/405 | 服务器内部错误 |

## 安全特性

- 密码使用 bcrypt 加密存储
- 所有数据库查询使用参数化查询，防止 SQL 注入
- 响应头设置 X-Content-Type-Options、X-Frame-Options、X-XSS-Protection
- 登录接口 60 秒内最多 5 次请求（基于 IP）
- 注册接口 60 秒内最多 3 次请求（基于 IP）
- 验证码发送 60 秒内最多 1 次，每日最多 10 次（基于邮箱）
- 验证码有效期 5 分钟，6 位纯数字
- 重置密码接口 60 秒内最多 3 次请求（基于 IP）
- JWT Token 有效期 24 小时

## 扩展指南

本项目采用模块化分层架构，新增模块时只需：

1. 在 `models/` 下创建数据模型
2. 在 `services/` 下创建业务服务
3. 在 `controllers/` 下创建控制器
4. 在 `routes/` 下创建路由蓝图
5. 在 `app.py` 中注册新蓝图

现有的 `token_required` 和 `require_role` 装饰器可直接复用。

## 配置说明

配置项通过 `config.py` 集中管理，支持环境变量覆盖：

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| MYSQL_HOST | localhost | 数据库地址 |
| MYSQL_PORT | 3306 | 数据库端口 |
| MYSQL_USER | root | 数据库用户 |
| MYSQL_PASSWORD | (空) | 数据库密码，必填 |
| MYSQL_DATABASE | ecomai_auth | 数据库名 |
| SECRET_KEY | dev-only-change-me-* | Flask 密钥，生产必改 |
| JWT_SECRET_KEY | dev-only-change-me-* | JWT 签名密钥，生产必改 |
| INVITE_CODE_ENCRYPTION_KEY | dev-only-change-me-* | 邀请码 AES 加密密钥，生产必改 |
| USER_AI_KEY_ENCRYPTION_KEY | dev-only-change-me-* | 用户自备 API Key 加密密钥，生产必改 |
| FLASK_ENV | default | 运行环境（development / production / testing）|
| SMTP_SERVER | smtp.qq.com | SMTP 服务器 |
| SMTP_PORT | 465 | SMTP 端口 |
| SMTP_USE_SSL | true | 是否使用 SSL |
| SMTP_USERNAME | (空) | 邮件服务发件邮箱，必填 |
| SMTP_PASSWORD | (空) | 邮件服务授权码，必填 |
| REDIS_URL | redis://localhost:6379/0 | Redis 连接串 |
| TASK_RESULT_TTL | 86400 | 任务状态保留秒数 |

> 完整清单与说明见 [docs/QUICKSTART.md](../docs/QUICKSTART.md) 与 [docs/SECURITY.md](../docs/SECURITY.md)。
> 代码内不保留任何真实凭据，`.env` 文件已被 `.gitignore` 排除。

### 验证码配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| 验证码长度 | 6 位 | 纯数字 |
| 有效期 | 300 秒（5 分钟）| `VERIFICATION_CODE_EXPIRE` |
| 发送频率限制 | 60 秒内 1 次 | `VERIFICATION_CODE_SEND_WINDOW` |
| 每日发送上限 | 10 次 | `VERIFICATION_CODE_DAILY_LIMIT` |