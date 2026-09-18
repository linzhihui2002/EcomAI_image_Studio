# syntax=docker/dockerfile:1

# ============================================================
# EcomAI Studio 前端镜像
# 阶段 1：Node 构建 Vue 3 + Vite 静态产物（含 .gz 预压缩文件）
# 阶段 2：Nginx 托管静态资源，并反向代理 /api 到后端容器
# 构建上下文：ecom-ai-studio/
# ============================================================

FROM node:20-alpine AS builder

WORKDIR /app

# 仅拷贝依赖清单，命中缓存时可跳过重复安装
COPY package.json package-lock.json ./
RUN npm ci

# 拷贝源码并构建
COPY . .
RUN npm run build

# ------------------------------------------------------------

FROM nginx:1.27-alpine AS runtime

ENV TZ=Asia/Shanghai

# 使用自定义站点配置（SPA 回退 + /api 反向代理 + SSE 免缓冲）
RUN rm -f /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/default.conf

# 构建产物（含 vite-plugin-compression 生成的 .gz，由 nginx gzip_static 直接命中）
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -qO- http://127.0.0.1/healthz || exit 1

CMD ["nginx", "-g", "daemon off;"]
