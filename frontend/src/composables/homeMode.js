import { reactive, watch } from 'vue'
import { authState } from './auth'
import { mergeAccountHistory } from './searchHistory'

// v3.3.96 首页模式：经典 classic / 简洁 simple（默认经典），与小程序同一套规则
// - 游客：只存本机浏览器
// - 登录用户：存账号（PATCH /api/me/prefs）；登录时账号有值用账号，没有就把本机值写上去；退出登录恢复本机值
// - 启动时同步读本机缓存直接渲染，不先闪经典首页
const GUEST = 'skp_home_mode'
const LAST = 'skp_home_mode_last'
const DIRTY = 'skp_home_mode_dirty' // 登录用户切换后没保存到账号（断网等）：下次以它为准并补传
const ok = (m) => (m === 'simple' || m === 'classic' ? m : '')
const get = (k) => {
  try {
    return localStorage.getItem(k) || ''
  } catch {
    return ''
  }
}
const set = (k, v) => {
  try {
    v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v)
  } catch {}
}
const dirty = () => {
  try {
    return JSON.parse(get(DIRTY) || 'null')
  } catch {
    return null
  }
}

export const homeMode = reactive({ value: ok(get(LAST)) || ok(get(GUEST)) || 'classic' })
// 简洁模式是否已经出了结果（加入栏、首页其他浮层据此显示）
export const simpleUi = reactive({ results: false })

function show(m) {
  homeMode.value = m
  set(LAST, m)
}

async function patch(m) {
  const { api } = await import('../api') // 动态引用，避免 api.js ↔ auth.js 循环依赖
  return api('/api/me/prefs', { method: 'PATCH', body: { home_mode: m } })
}

export async function setHomeMode(m) {
  m = ok(m) || 'classic'
  show(m)
  if (authState.user) {
    authState.user.prefs = { ...(authState.user.prefs || {}), home_mode: m }
    set(DIRTY, JSON.stringify({ uid: authState.user.id, m }))
    try {
      await patch(m)
      set(DIRTY, null)
    } catch {}
  } else set(GUEST, m)
}

watch(
  () => [authState.ready, authState.user && authState.user.id],
  async ([ready, uid]) => {
    if (!ready) return
    const guest = ok(get(GUEST)) || 'classic'
    if (!uid) return authState.token ? undefined : show(guest) // 有令牌但没确认登录（断网）：保持上次的模式
    const prefs = authState.user.prefs || {}
    const d = dirty()
    if (d && d.uid === uid && ok(d.m)) {
      show(d.m)
      try {
        await patch(d.m)
        authState.user.prefs = { ...prefs, home_mode: d.m }
        set(DIRTY, null)
      } catch {}
    } else if (ok(prefs.home_mode)) show(prefs.home_mode)
    else {
      show(guest)
      try {
        await patch(guest)
        authState.user.prefs = { ...prefs, home_mode: guest }
      } catch {}
    }
    mergeAccountHistory(prefs.search_history)
  },
  { immediate: true },
)
