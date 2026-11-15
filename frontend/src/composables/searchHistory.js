import { ref, watch } from 'vue'
import { authState } from './auth'

// 搜索历史（最多 10 条、每条 ≤200 字，存完整原文，列表只显示第一行），与小程序同一套规则：
// - 游客只存本机浏览器
// - v3.3.96 登录用户：本机先写，防抖上传到账号（PATCH /api/me/prefs search_history）；登录时与账号历史合并去重；退出恢复本机记录
const KEY = 'skp_search_history'
const MAX = 10
const clean = (arr) => {
  const out = []
  for (const x of Array.isArray(arr) ? arr : []) {
    const s = typeof x === 'string' ? x.trim().slice(0, 200) : ''
    if (s && !out.some((y) => y.toLowerCase() === s.toLowerCase())) out.push(s)
  }
  return out.slice(0, MAX)
}
function read() {
  try {
    return clean(JSON.parse(localStorage.getItem(KEY) || '[]'))
  } catch {
    return []
  }
}
export const searchHistory = ref(read())

let upTimer
function write() {
  if (!authState.user) {
    try {
      localStorage.setItem(KEY, JSON.stringify(searchHistory.value))
    } catch {}
    return
  }
  clearTimeout(upTimer)
  const list = searchHistory.value.slice()
  upTimer = setTimeout(async () => {
    try {
      const { api } = await import('../api') // 动态引用，避免 api.js ↔ auth.js 循环依赖
      await api('/api/me/prefs', { method: 'PATCH', body: { search_history: list } })
      if (authState.user) authState.user.prefs = { ...(authState.user.prefs || {}), search_history: list }
    } catch {}
  }, 800)
}

/** 登录后：账号历史和本机历史合并（账号在前），有变化再上传 */
export function mergeAccountHistory(acct) {
  const a = clean(acct)
  const merged = clean([...a, ...read()])
  searchHistory.value = merged
  if (merged.join('\n') !== a.join('\n')) write()
}
watch(
  () => authState.user && authState.user.id,
  (uid, old) => {
    if (!uid && old) searchHistory.value = read()
  },
)

export function rememberSearch(q) {
  const s = (q || '').trim().slice(0, 200)
  if (s.length < 2) return
  searchHistory.value = clean([s, ...searchHistory.value])
  write()
}
export function forgetSearch(q) {
  searchHistory.value = searchHistory.value.filter((x) => x !== q)
  write()
}
export function clearSearchHistory() {
  searchHistory.value = []
  write()
}
