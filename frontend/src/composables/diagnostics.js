// 反馈 Bug 时附带的诊断信息：最近的前端报错与失败的接口请求（只保存在内存里，用户勾选后才随反馈提交）
const MAX = 20
const errors = []
const failures = []

function push(list, entry) {
  list.push({ ...entry, at: new Date().toISOString() })
  if (list.length > MAX) list.shift()
}

export function recordFailure(method, path, status, message) {
  push(failures, { method, path: path.slice(0, 200), status, message: String(message).slice(0, 200) })
}

export function installErrorCapture() {
  addEventListener('error', (e) => push(errors, { message: String(e.message || e.error || '').slice(0, 300), source: e.filename, line: e.lineno }))
  addEventListener('unhandledrejection', (e) => push(errors, { message: String(e.reason?.message || e.reason || '').slice(0, 300) }))
}

export function collectDiagnostics() {
  return {
    page: location.pathname + location.search,
    ua: navigator.userAgent,
    screen: `${screen.width}x${screen.height} @${devicePixelRatio}`,
    viewport: `${innerWidth}x${innerHeight}`,
    lang: navigator.language,
    time: new Date().toISOString(),
    errors: [...errors],
    failed_requests: [...failures],
  }
}
