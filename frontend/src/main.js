import { createApp } from 'vue'
import { installErrorReporting } from './composables/errorReport'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import { reveal } from './directives/reveal'
import { scrollTrap } from './directives/scrollTrap'
import { installRipple, magnet, tilt } from './composables/motion'
import { trackRoute } from './composables/analytics'
import { authState, initAuth, isAdminUser, requireLogin } from './composables/auth'
import { installErrorCapture } from './composables/diagnostics'
import './style.css'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      component: () => import('./views/HomeView.vue'),
      // 详情以抽屉形式叠在列表上，链接可直接打开，返回即关闭
      children: [{ path: 'items/:id', component: () => import('./views/ItemView.vue'), props: true }],
    },
    // 旧的编辑页已并入管理端「内容管理」
    { path: '/items/:id/edit', component: { render: () => null }, beforeEnter: (to) => (location.replace(`/admin/content?id=${to.params.id}`), false) },
    {
      path: '/rankings',
      component: () => import('./views/RankingsView.vue'),
      children: [{ path: 'items/:id', component: () => import('./views/ItemView.vue'), props: true }],
    },
    // v3.0「新增 Skill」并入首页搜索框的 GitHub 标签；旧链接跳过去
    { path: '/add', redirect: (to) => ({ path: '/', query: { scope: 'github', ...(to.query.tab === 'image' ? { shot: '1' } : {}) } }) },
    {
      // v2.3 对比结果（可分享）；里面点条目在抽屉里看详情
      path: '/compare/:cid',
      component: () => import('./views/CompareView.vue'),
      props: true,
      children: [{ path: 'items/:id', component: () => import('./views/ItemView.vue'), props: true }],
    },
    {
      // v3.2「口袋」：我的收藏 + 我的 AI 对比；旧的 /favorites 链接跳过来
      path: '/pocket',
      component: () => import('./views/PocketView.vue'),
      children: [{ path: 'items/:id', component: () => import('./views/ItemView.vue'), props: true }],
    },
    {
      // v3.3 公开分享的收藏分类（只读）
      path: '/s/:token',
      component: () => import('./views/SharedView.vue'),
      props: true,
      children: [{ path: 'items/:id', component: () => import('./views/ItemView.vue'), props: true }],
    },
    { path: '/favorites', redirect: (to) => ({ path: '/pocket', query: to.query }) },
    { path: '/favorites/items/:id', redirect: (to) => ({ path: `/pocket/items/${to.params.id}`, query: to.query }) },
    {
      path: '/me',
      component: () => import('./views/MeView.vue'),
      children: [{ path: 'items/:id', component: () => import('./views/ItemView.vue'), props: true }],
    },
    // 旧版管理后台已下线：旧链接跳到新管理端（/admin）对应的页面
    { path: '/manage/items/:id', redirect: (to) => `/items/${to.params.id}` },
    {
      path: '/manage',
      component: { render: () => null },
      beforeEnter: (to) => {
        const tab = to.query.tab === 'feed' || !to.query.tab ? '' : to.query.tab
        location.replace(`/admin/${tab}${to.query.task ? `?task=${to.query.task}` : ''}`)
        return false
      },
    },
    { path: '/terms', component: () => import('./views/LegalView.vue') },
    { path: '/privacy', component: () => import('./views/LegalView.vue') },
    { path: '/categories', redirect: { path: '/manage', query: { tab: 'categories' } } },
    // v3.1：常被猜到的「提交」地址指向 GitHub 收录（未登录会弹登录框）；其余未知地址显示 404
    { path: '/submit', redirect: { path: '/', query: { scope: 'github' } } },
    { path: '/:pathMatch(.*)*', component: () => import('./views/NotFoundView.vue') },
  ],
  scrollBehavior(to, from, saved) {
    // 打开 / 关闭抽屉时保持列表滚动位置
    const isSheet = (r) => r.matched.length > 1
    if (isSheet(to) || isSheet(from)) return false
    return saved || { top: 0 }
  },
})

// 需要登录的页面：未登录先弹登录框，关掉就留在原页面；管理页只对管理员开放
const authReady = initAuth()
router.beforeEach(async (to, from) => {
  if (!to.meta.login && !to.meta.admin) return true
  await authReady
  if (!authState.user) {
    const ok = await requireLogin(to.meta.login || '管理功能需要管理员账号登录')
    if (!ok) return from.matched.length ? false : '/'
  }
  if (to.meta.admin && !isAdminUser()) return { path: '/', query: { denied: '1' } }
  return true
})

router.afterEach((to, from, failure) => !failure && trackRoute(to))

// v3.3.67 发版后还开着旧页面的人，切页面时会因为旧的页面文件已被替换而加载失败：自动刷新一次换成新版本
// （同一个地址 30 秒内只自动刷新一次，免得真的打不开时无限刷新）
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
    reloadForNewVersion(to?.fullPath || window.location.pathname)
  }
})

installErrorCapture()
installRipple()
const app = createApp(App)
installErrorReporting(app) // v3.3.66 报错上报（后台运行监控查看）
app.use(router).directive('reveal', reveal).directive('magnet', magnet).directive('tilt', tilt).directive('scroll-trap', scrollTrap).mount('#app')
