import { ref } from 'vue'

// v3.3 搜索历史：只存在本机浏览器（最多 10 条），不上传
const KEY = 'skp_search_history'

function read() {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) || '[]')
    return Array.isArray(v) ? v.filter((x) => typeof x === 'string').slice(0, 10) : []
  } catch {
    return []
  }
}
export const searchHistory = ref(read())

function write() {
  try {
    localStorage.setItem(KEY, JSON.stringify(searchHistory.value))
  } catch {}
}
export function rememberSearch(q) {
  const s = (q || '').trim()
  if (s.length < 2 || s.length > 60) return
  searchHistory.value = [s, ...searchHistory.value.filter((x) => x.toLowerCase() !== s.toLowerCase())].slice(0, 10)
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
