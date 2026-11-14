import { reactive } from 'vue'
import { api } from '../../api'

// 驳回 / 处置原因模板：按场景（item_reject、comment_reject、comment_delete、share_close…）从后端取，
// 取不到或还没有配置时用前端常量兜底。同一场景只请求一次。
//   const templates = await reasonTemplates('comment_reject', REASONS.commentReject)
const cache = reactive({})
const pending = {}

const SCOPES = ['item_reject', 'item_revoke', 'comment_reject', 'comment_delete', 'share_close', 'takedown_approve', 'takedown_reject'] // 后端支持的场景

export async function reasonTemplates(scope, fallback = []) {
  if (!SCOPES.includes(scope)) return fallback
  if (cache[scope]) return cache[scope]
  pending[scope] ||= api(`/api/admin/reason-templates?scope=${scope}`)
    .then((d) => {
      const list = (d.items || []).filter((t) => t.enabled !== false).map((t) => t.text)
      cache[scope] = list.length ? list : fallback
      return cache[scope]
    })
    .catch(() => fallback)
    .finally(() => delete pending[scope])
  return pending[scope]
}
// 模板被编辑后让缓存失效
export const resetReasonTemplates = (scope) => (scope ? delete cache[scope] : Object.keys(cache).forEach((k) => delete cache[k]))
