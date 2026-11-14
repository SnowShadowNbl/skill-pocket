import { track } from './analytics'
import { reactive } from 'vue'
import { api, isCancelled } from '../api'
import { toast } from './toast'

// 收藏状态的全局缓存：详情抽屉里点了收藏，背后列表里的卡片同步变化
export const favState = reactive({ map: {}, count: null })

export function isFav(item) {
  return item.id in favState.map ? favState.map[item.id] : !!item.favorited
}

export async function toggleFav(item) {
  const next = !isFav(item)
  track(next ? 'favorite' : 'unfavorite', { item_id: item.id })
  favState.map[item.id] = next // 先改界面，失败再回滚
  if (favState.count != null) favState.count += next ? 1 : -1
  try {
    const r = await api(`/api/items/${item.id}/favorite`, { method: 'POST', body: { on: next } })
    favState.map[item.id] = r.favorited
    favState.count = r.favorites
    toast(next ? '已收藏' : '已取消收藏', 'success', 1400)
    return r.favorited
  } catch (e) {
    favState.map[item.id] = !next
    if (favState.count != null) favState.count += next ? -1 : 1
    if (!isCancelled(e)) toast(e.message, 'error')
    return !next
  }
}

// ---- 收藏分类 ----
// structure：/api/favorites/structure 的缓存（系统维度 + 自定义维度 + 各分类数量）
export const favTree = reactive({ data: null, loading: false })

export async function loadFavTree() {
  favTree.loading = true
  try {
    favTree.data = await api('/api/favorites/structure')
    favState.count = favTree.data.total
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  } finally {
    favTree.loading = false
  }
  return favTree.data
}

export function customDims() {
  return favTree.data?.dimensions || []
}

// 最近用过的分类排在前面，其余按用户排的顺序
export function foldersByRecent(dim) {
  return [...(dim?.folders || [])].sort((a, b) => {
    const ta = a.last_used_at ? Date.parse(a.last_used_at) : 0
    const tb = b.last_used_at ? Date.parse(b.last_used_at) : 0
    return tb - ta || dim.folders.indexOf(a) - dim.folders.indexOf(b)
  })
}

export async function createFolder(dimensionId, name, emoji = '') {
  const f = await api('/api/favorites/folders', { method: 'POST', body: { dimension_id: dimensionId, name, emoji } })
  await loadFavTree()
  return f
}

export async function setItemFolders(itemId, dimensionId, folderIds) {
  const r = await api(`/api/favorites/${itemId}/folders`, { method: 'PUT', body: { dimension_id: dimensionId, folder_ids: folderIds } })
  loadFavTree()
  return r.folder_ids
}
