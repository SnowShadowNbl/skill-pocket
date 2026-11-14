import { reactive } from 'vue'

// 登录态：令牌存在 localStorage（30 天滑动有效），用户信息启动时向 /api/auth/me 确认一次。
// 需要登录的操作调用 requireLogin()：已登录直接通过；未登录弹出登录框，登录成功后继续刚才的操作。
const KEY = 'skillpocket.token'

function readToken() {
  try {
    return localStorage.getItem(KEY) || ''
  } catch {
    return ''
  }
}

export const authState = reactive({
  token: readToken(),
  user: null,
  ready: false,
  version: 0, // 每次登录 / 退出 +1
  modal: { open: false, reason: '' },
})

let waiters = []

export function isLoggedIn() {
  return !!authState.user
}

export function isAdminUser() {
  return ['admin', 'subadmin'].includes(authState.user?.role)
}

export function setSession(token, user) {
  authState.token = token
  authState.user = user
  authState.version++
  try {
    localStorage.setItem(KEY, token)
  } catch {}
}

export function clearSession() {
  if (authState.user) authState.version++
  authState.token = ''
  authState.user = null
  try {
    localStorage.removeItem(KEY)
  } catch {}
}

let initPromise = null

export function initAuth() {
  initPromise ||= doInit()
  return initPromise
}

async function doInit() {
  if (!authState.token) {
    authState.ready = true
    return
  }
  try {
    const res = await fetch('/api/auth/me', { headers: { authorization: `Bearer ${authState.token}` } })
    const data = await res.json()
    if (data.user) authState.user = data.user
    else clearSession()
  } catch {
    // 网络问题时保留令牌，下次请求再确认
  } finally {
    authState.ready = true
  }
}

/** 未登录时弹出登录框，登录成功 resolve(true)，关闭 resolve(false)。 */
export function requireLogin(reason = '') {
  if (authState.user) return Promise.resolve(true)
  authState.modal.reason = reason
  authState.modal.open = true
  import('./analytics').then((m) => m.track('login_open', { reason }))
  return new Promise((resolve) => waiters.push(resolve))
}

export function finishLogin(ok) {
  authState.modal.open = false
  const w = waiters
  waiters = []
  w.forEach((r) => r(ok))
}

export async function logout() {
  import('./analytics').then((m) => m.track('logout'))
  try {
    await fetch('/api/auth/logout', { method: 'POST', headers: { authorization: `Bearer ${authState.token}` } })
  } catch {}
  clearSession()
}
