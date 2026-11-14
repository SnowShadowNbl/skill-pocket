import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import { installErrorCapture } from '../composables/diagnostics'
import { installRipple } from '../composables/motion'
import AdminApp from './AdminApp.vue'
import { MODULES } from './modules'
import './admin.css'

// P4 管理端（方案 A）
const router = createRouter({
  history: createWebHistory('/admin/'),
  routes: [
    ...MODULES.map((m) => ({ path: m.path, name: m.key, component: m.view, meta: { module: m } })),
    { path: '/:rest(.*)*', redirect: '/' },
  ],
  // 换页回到顶部；只改 query（筛选、开关详情抽屉）不动；前进后退恢复原位置
  scrollBehavior: (to, from, saved) => saved || (to.path === from.path ? false : { top: 0 }),
})

// 发版后还开着旧页面的人，切页面时旧的页面文件已被替换而加载失败：自动刷新一次换成新版本（同一地址 30 秒内只刷一次）
function reloadForNewVersion(path) {
  try {
    const key = `skillpocket.reload:${path}`
    const last = Number(sessionStorage.getItem(key) || 0)
    if (Date.now() - last < 30000) return false
    sessionStorage.setItem(key, String(Date.now()))
  } catch {
    // 无痕模式下 sessionStorage 不可用：仍然刷新一次
  }
  window.location.assign(path)
  return true
}
window.addEventListener('vite:preloadError', (e) => {
  if (reloadForNewVersion(window.location.pathname + window.location.search)) e.preventDefault()
})
router.onError((err, to) => {
  if (/dynamically imported module|Importing a module script failed|error loading dynamically/i.test(String(err?.message || err))) {
    reloadForNewVersion(to?.fullPath ? `/admin${to.fullPath}` : window.location.pathname)
  }
})

installErrorCapture()
installRipple('.btn, .seg > button, .rp')
createApp(AdminApp).use(router).mount('#app')
