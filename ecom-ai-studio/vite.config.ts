import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import compression from 'vite-plugin-compression'
import { resolve } from 'path'

export default defineConfig({
  plugins: [
    vue(),
    // 构建时生成 .gz 文件（nginx 可直接 serve 预压缩静态资源）
    compression({ algorithm: 'gzip', ext: '.gz', threshold: 1024, deleteOriginFile: false }),
    // 构建时生成 .br 文件（brotli 压缩率更高）
    compression({ algorithm: 'brotliCompress', ext: '.br', threshold: 1024, deleteOriginFile: false }),
  ],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  server: {
    port: 5173,
    host: '0.0.0.0',
    allowedHosts: true,
    proxy: {
      '/api': {
        target: 'http://localhost:5001',
        changeOrigin: true,
        timeout: 600000,        // 10 分钟（避免代理层过早断开）
        proxyTimeout: 600000,   // 10 分钟
      },
    },
  },
  build: {
    // 目标浏览器（减少 polyfill 体积）
    target: 'es2020',
    // 启用 CSS 代码分割
    cssCodeSplit: true,
    //  chunk 大小警告阈值（KB）
    chunkSizeWarningLimit: 500,
    rollupOptions: {
      output: {
        // 手动分包：将稳定的大型依赖分离为独立 vendor chunk
        manualChunks: {
          // Vue 核心生态
          'vendor-vue': ['vue', 'vue-router', 'pinia'],
          // UI 组件库
          'vendor-ui': ['radix-vue', 'lucide-vue-next'],
          // 工具库
          'vendor-utils': ['clsx', 'tailwind-merge', 'class-variance-authority'],
        },
      },
    },
  },
})