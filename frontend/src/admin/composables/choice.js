import { reactive } from 'vue'

// 「选一项」确认弹窗的状态。askChoice() 返回 Promise<选中的值 | null>，点取消得到 null
//   const id = await askChoice({ title: '改分类', impact: '将修改 12 个条目的分类', options: [{ value, label, group? }], okText: '修改' })
export const choiceState = reactive({ open: false, opts: {}, value: '' })
let resolver = null

export function askChoice(opts) {
  resolver?.(null)
  Object.assign(choiceState, { open: true, opts, value: '' })
  return new Promise((r) => (resolver = r))
}

export function closeChoice(ok) {
  choiceState.open = false
  const r = resolver
  resolver = null
  r?.(ok && choiceState.value !== '' ? choiceState.value : null)
}
