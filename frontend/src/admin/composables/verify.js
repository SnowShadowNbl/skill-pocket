import { reactive } from 'vue'
import { api, ApiError } from '../../api'

// 高危操作的二次验证状态。askVerify() 返回 Promise<验证令牌 | null>，取消得到 null；令牌随高危接口一起提交（verify_token）
//   const token = await askVerify({ action: 'export_email', title: '导出带邮箱的用户' })
//   if (token == null) return
export const verifyState = reactive({ open: false, opts: {} })
let resolver = null

export function askVerify(opts) {
  resolver?.(null)
  Object.assign(verifyState, { open: true, opts })
  return new Promise((r) => (resolver = r))
}
export function finishVerify(token) {
  verifyState.open = false
  const r = resolver
  resolver = null
  r?.(token || null)
}

// 调用高危接口：缺令牌时（403 verify_required）自动弹出二次验证，通过后带上令牌重试一次。
//   await callVerified(`/api/admin/users/${id}/email`, { method: 'PUT', body }, { action: 'change_email', title: '修改用户邮箱' })
//   用户取消验证时抛出 cancelled（isCancelled 为真），调用方照常忽略即可
export async function callVerified(path, opts, { action, title }) {
  try {
    return await api(path, opts)
  } catch (e) {
    if (e?.code !== 'verify_required') throw e
    const token = await askVerify({ action: e.action || action, title })
    if (token == null) throw new ApiError(0, 'cancelled')
    return api(`${path}${path.includes('?') ? '&' : '?'}verify_token=${encodeURIComponent(token)}`, opts)
  }
}
