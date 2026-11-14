import { reactive } from 'vue'
import { api } from '../api'
import { requireLogin } from './auth'
import { toast } from './toast'

// v3.3 站内消息（右上角铃铛）与分类订阅
export const noteState = reactive({ unread: 0, items: null, subs: null, subList: [] })

export async function loadNotes() {
  try {
    const r = await api('/api/notifications')
    noteState.unread = r.unread
    noteState.items = r.items
  } catch {}
}
// v3.3.20 已读改为逐条：打开铃铛不再全部标已读；点哪条只去掉哪条的提醒点；另有「全部已读」
export async function markNoteRead(n) {
  if (!n || n.read) return
  n.read = true // 先在界面上去掉提醒点
  noteState.unread = Math.max(0, noteState.unread - 1)
  try {
    noteState.unread = (await api(`/api/notifications/${n.id}/read`, { method: 'POST' })).unread
  } catch {}
}
export async function markAllNotesRead() {
  if (!noteState.unread) return
  noteState.unread = 0
  noteState.items?.forEach((n) => (n.read = true))
  try {
    await api('/api/notifications/read', { method: 'POST' })
  } catch {
    loadNotes()
  }
}
export async function loadSubs() {
  try {
    const rows = await api('/api/subscriptions')
    noteState.subList = rows.filter((s, i) => rows.findIndex((x) => x.code === s.code) === i) // 去重
    noteState.subs = noteState.subList.map((s) => s.code)
  } catch {
    noteState.subs = []
    noteState.subList = []
  }
}
export const isSubscribed = (code) => !!noteState.subs?.includes(code)

// v3.3.7「去订阅」：带到首页并默认选中第一个大类，标题旁的「订阅上新」按钮会闪一下提示
let firstGroup = null
export async function goSubscribe(router) {
  if (!firstGroup) {
    try {
      firstGroup = (await api('/api/categories'))[0]?.code || null
    } catch {}
  }
  await router.push({ path: '/', query: { ...(firstGroup ? { category: firstGroup } : {}), sub: '1' } })
}

// v3.3.8：连点同一个分类时，上一次请求没返回前忽略后面的点击（原来会追加出两个相同的订阅标签）；
// 点一下立即切换显示，请求失败再改回来；完成后以服务器的订阅列表为准（去重）
const busySubs = new Set()
function setSub(code, name, on) {
  const others = (noteState.subList || []).filter((s) => s.code !== code)
  noteState.subList = on ? [...others, { code, name }] : others
  noteState.subs = noteState.subList.map((s) => s.code)
}

export async function toggleSub(code, name) {
  if (busySubs.has(code)) return
  busySubs.add(code)
  try {
    if (!(await requireLogin('登录后可以订阅分类上新'))) return
    if (!noteState.subs) await loadSubs()
    const on = isSubscribed(code)
    setSub(code, name, !on)
    try {
      await api(`/api/subscriptions/${code}`, { method: on ? 'DELETE' : 'POST' })
      toast(on ? `已取消订阅「${name}」` : `已订阅「${name}」，有新收录会在右上角铃铛里提醒你`, 'success', 3000)
    } catch (e) {
      setSub(code, name, on)
      toast(e.message, 'error')
    }
    await loadSubs()
  } finally {
    busySubs.delete(code)
  }
}
