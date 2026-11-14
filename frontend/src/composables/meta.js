import { reactive } from 'vue'
import { api } from '../api'

// /api/meta 的全局缓存：AI 模型名、使用类型列表、统计数字等
export const meta = reactive({ data: null })
let pending = null

export function loadMeta(force = false) {
  if (meta.data && !force) return Promise.resolve(meta.data)
  if (!pending || force) {
    pending = api('/api/meta')
      .then((d) => (meta.data = d))
      .catch(() => null)
      .finally(() => (pending = null))
  }
  return pending
}

export function kindList() {
  return meta.data?.kinds || []
}
