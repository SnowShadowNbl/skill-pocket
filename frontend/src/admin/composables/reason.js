import { reactive } from 'vue'

// 「填写原因」确认弹窗的状态。askReason() 返回 Promise<原因 | null>，点取消得到 null
//   const reason = await askReason({ title: '停用「张三」？', impact: '将停用 1 个账号', templates: REASONS.disable, danger: true, okText: '停用' })
//   选项：title / impact（影响摘要）/ min（最少字数，默认 4）/ max（默认 300）/ templates / danger / okText / placeholder
export const reasonState = reactive({ open: false, opts: {}, value: '' })
let resolver = null

export function askReason(opts) {
  resolver?.(null)
  Object.assign(reasonState, { open: true, opts: { min: 4, max: 300, templates: [], ...opts }, value: opts.value || '' })
  return new Promise((r) => (resolver = r))
}

export function closeReason(ok) {
  reasonState.open = false
  const r = resolver
  resolver = null
  r?.(ok ? reasonState.value.trim() : null)
}
