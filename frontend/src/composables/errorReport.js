// v3.3.66 客户端报错上报（后台「运行监控」查看）：脚本错误、未处理的异步错误、接口 5xx / 断网。
// 同一条报错一个页面只报一次，每个页面会话最多报 20 条；上报失败就算了，绝不影响页面。
const CLIENT_VERSION = typeof __BUILD_VERSION__ !== 'undefined' ? __BUILD_VERSION__ : ''
const MAX = 20
const seen = new Set()
let sent = 0

export function reportError(kind, message, stack = '') {
  try {
    const msg = String(message || '').slice(0, 2000)
    if (!msg || sent >= MAX) return
    const key = `${kind}|${msg}`
    if (seen.has(key)) return
    seen.add(key)
    sent += 1
    const token = localStorage.getItem('skillpocket.token')
    fetch('/api/client-errors', {
      method: 'POST',
      keepalive: true,
      headers: {
        'content-type': 'application/json',
        'x-client': 'web',
        ...(CLIENT_VERSION ? { 'x-client-version': CLIENT_VERSION } : {}),
        ...(token ? { authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ kind, message: msg, stack: String(stack || '').slice(0, 8000), page: location.pathname, version: CLIENT_VERSION }),
    }).catch(() => {})
  } catch {
    // 上报本身出错时什么也不做
  }
}

export function installErrorReporting(app) {
  window.addEventListener('error', (e) => {
    // 图片等资源加载失败也会触发 error 事件，没有 message，跳过
    if (!e.message) return
    reportError('js_error', e.message, e.error?.stack || `${e.filename}:${e.lineno}:${e.colno}`)
  })
  window.addEventListener('unhandledrejection', (e) => {
    const r = e.reason
    if (r && r.name === 'ApiError') return // 接口错误在 api.js 里单独报（只报 5xx / 断网）
    reportError('promise', r?.message || String(r), r?.stack || '')
  })
  const prev = app.config.errorHandler
  app.config.errorHandler = (err, vm, info) => {
    reportError('js_error', `${err?.message || err}（${info}）`, err?.stack || '')
    if (prev) prev(err, vm, info)
    else console.error(err) // eslint-disable-line no-console
  }
}
