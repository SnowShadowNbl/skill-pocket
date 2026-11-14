import { resolve } from 'node:path'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'

const backend = process.env.API_TARGET || 'http://127.0.0.1:8001'

// 管理端是独立入口（admin.html），/admin 下的路径都交给它（开发服务器里的 history 回退）
const adminFallback = {
  name: 'admin-fallback',
  configureServer(server) {
    server.middlewares.use((req, _res, next) => {
      if (/^\/admin(\/[^.]*)?(\?.*)?$/.test(req.url)) req.url = '/admin.html'
      next()
    })
  },
}

export default defineConfig({
  plugins: [vue(), tailwindcss(), adminFallback],
  // v3.3.37 网页客户端版本：构建时间（北京时间），随请求头 X-Client-Version 上报，后台按版本排查问题
  define: { __BUILD_VERSION__: JSON.stringify('web-' + new Date(Date.now() + 8 * 3600e3).toISOString().slice(0, 16).replace(/[-:]/g, '').replace('T', '.')) },
  build: {
    rollupOptions: { input: { main: resolve(__dirname, 'index.html'), admin: resolve(__dirname, 'admin.html') } },
  },
  server: {
    host: true, // 局域网内手机可直接访问调试
    port: 5173,
    // Windows 下原生文件监听在批量写文件时会抛 EBUSY 导致 dev server 退出，改用轮询
    watch: { usePolling: true, interval: 300 },
    proxy: {
      '/api': { target: backend, ws: true },
      '/media': backend,
    },
  },
})
