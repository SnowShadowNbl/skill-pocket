import { authState } from './auth'

// 用户探真：浏览器内的游客编号 + 行为事件。攒一小批再上报，页面隐藏 / 关闭时用 keepalive 发出去
const KEY = 'skp_vid'
const queue = []
let timer = null

function newId() {
  const a = new Uint8Array(12)
  crypto.getRandomValues(a)
  return 'v_' + Array.from(a, (b) => b.toString(36).padStart(2, '0')).join('').slice(0, 20)
}

function readVid() {
  try {
    let v = localStorage.getItem(KEY)
    if (!v || !/^[A-Za-z0-9_-]{8,40}$/.test(v)) {
      v = newId()
      localStorage.setItem(KEY, v)
    }
    return v
  } catch {
    return newId() // 无痕模式等拿不到存储时，本次打开内保持同一个编号
  }
}

export const visitorId = readVid()
const landing = location.pathname + location.search
let referrer = document.referrer && !document.referrer.startsWith(location.origin) ? document.referrer : ''

function flush() {
  clearTimeout(timer)
  timer = null
  if (!queue.length) return
  const events = queue.splice(0, 50)
  const headers = { 'content-type': 'application/json', 'x-visitor-id': visitorId }
  if (authState.token) headers.authorization = `Bearer ${authState.token}`
  const body = JSON.stringify({ vid: visitorId, events, referrer, landing })
  referrer = ''
  fetch('/api/t', { method: 'POST', headers, body, keepalive: true }).catch(() => {})
  if (queue.length) flush()
}

/** 记录一个行为事件。name 必须是后端 EVENTS 里列出的名字 */
export function track(name, props = {}) {
  queue.push({ name, props, page: location.pathname + location.search })
  if (queue.length >= 20) flush()
  else if (!timer) timer = setTimeout(flush, 3000)
}

let lastPath = ''
/** 路由切换后调用：记录页面浏览；详情页另记一次 item_view */
export function trackRoute(to) {
  if (to.fullPath === lastPath) return
  lastPath = to.fullPath
  track('page_view', { path: to.path, title: String(to.name || '') })
  const id = Number(to.params?.id)
  // v3.3：榜单、口袋、我的里打开的详情也记上（「为你推荐」要用浏览记录）
  if (id && /\/items\/\d+$/.test(to.path)) track('item_view', { item_id: id })
}

addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'hidden') flush()
})
addEventListener('pagehide', flush)
addEventListener('error', (e) => track('error', { message: String(e.message || '').slice(0, 200), src: String(e.filename || '').slice(-80) }))
addEventListener('unhandledrejection', (e) => track('error', { message: String(e.reason?.message || e.reason || '').slice(0, 200) }))
