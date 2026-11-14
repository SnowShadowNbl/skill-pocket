import { authState, clearSession, requireLogin } from './composables/auth'
import { visitorId } from './composables/analytics'
import { recordFailure } from './composables/diagnostics'
import { reportError } from './composables/errorReport'
import { bumpTasks } from './composables/tasks'

export class ApiError extends Error {
  constructor(status, message, code = '') {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code // v3.3.37 新接口的错误码（如 reason_required / merged_account / count_changed）
  }
}

// v3.3.37 客户端标识：后台按端（PC / 手机网页 / 小程序）和版本统计；版本是这次构建的时间
const CLIENT_VERSION = typeof __BUILD_VERSION__ !== 'undefined' ? __BUILD_VERSION__ : ''

export function authHeaders() {
  // 游客编号随每个请求带上，服务端据此把登录、注册等事件归到同一个访客
  return authState.token ? { authorization: `Bearer ${authState.token}`, 'x-visitor-id': visitorId } : { 'x-visitor-id': visitorId }
}

/**
 * - 自动带上登录令牌；接口要求登录（401 + X-Login-Required）时弹出登录框，登录后自动重试一次；用户关掉登录框则抛出 cancelled
 * - opts.admin = true：管理员操作。未登录先弹登录框；登录的不是管理员时提示「需要管理员权限」
 */
export async function api(path, { method = 'GET', body, admin: needAdmin = false, _relogin = false } = {}) {
  if (needAdmin && !authState.user) {
    const ok = await requireLogin('这个操作需要管理员账号登录')
    if (!ok) throw new ApiError(401, 'cancelled')
  }
  const headers = { ...authHeaders(), 'x-client': 'web', ...(CLIENT_VERSION ? { 'x-client-version': CLIENT_VERSION } : {}) }
  if (body !== undefined) headers['content-type'] = 'application/json'

  let res
  try {
    res = await fetch(path, { method, headers, body: body !== undefined ? JSON.stringify(body) : undefined })
  } catch {
    recordFailure(method, path, 0, '网络错误')
    reportError('api_fail', `${method} ${path.split('?')[0]} 网络错误`)
    throw new ApiError(0, '网络错误，请检查网络后重试')
  }

  if (res.status === 401 && res.headers.get('x-login-required') && !_relogin) {
    if (authState.user) clearSession() // 令牌过期或被其他设备注销
    const ok = await requireLogin(needAdmin ? '这个操作需要管理员账号登录' : '')
    if (!ok) throw new ApiError(401, 'cancelled')
    return api(path, { method, body, admin: needAdmin, _relogin: true })
  }

  const data = await res.json().catch(() => null)
  if (res.ok && data && typeof data === 'object' && data.task_id) bumpTasks()
  if (!res.ok) {
    let msg = data?.detail
    let code = ''
    if (Array.isArray(msg)) msg = msg.map((d) => d.msg).join('；')
    else if (msg && typeof msg === 'object') {
      // v3.3.37 新接口的错误格式 {detail: {code, message}}；老接口 detail 仍是字符串
      code = msg.code || ''
      msg = msg.message || ''
    }
    msg = msg || `请求失败（${res.status}）`
    recordFailure(method, path, res.status, msg)
    if (res.status >= 500) reportError('api_fail', `${method} ${path.split('?')[0]} ${res.status}：${msg}`)
    throw new ApiError(res.status, msg, code)
  }
  return data
}

export function isCancelled(e) {
  return e?.message === 'cancelled'
}

export function formatTime(iso, withTime = true) {
  if (!iso) return '-'
  const d = new Date(iso)
  const p = (n) => String(n).padStart(2, '0')
  const date = `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
  return withTime ? `${date} ${p(d.getHours())}:${p(d.getMinutes())}` : date
}

/** 「3 分钟前」这类相对时间，超过一天显示日期 */
export function timeAgo(iso) {
  if (!iso) return ''
  const s = (Date.now() - new Date(iso).getTime()) / 1000
  if (s < 45) return '刚刚'
  if (s < 3600) return `${Math.round(s / 60)} 分钟前`
  if (s < 86400) return `${Math.round(s / 3600)} 小时前`
  return formatTime(iso)
}

export function formatStars(n) {
  if (n === null || n === undefined) return '-'
  if (n >= 10000) return (n / 1000).toFixed(n >= 100000 ? 0 : 1) + 'k'
  return n.toLocaleString()
}
