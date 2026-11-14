import { reactive } from 'vue'

// 主题对话框（替代 window.confirm / prompt）。
//   if (await confirmDialog({ title, message, danger: true })) …
//   const name = await promptDialog({ title, value, placeholder, maxlength, required })
//   点「取消」返回 null；点确定返回输入（可能是空字符串，可选填的原因留空也要能继续）；required 时没填不能点确定
export const dialogState = reactive({ open: false, kind: 'confirm', opts: {}, value: '' })
let resolver = null

function show(kind, opts) {
  resolver?.(kind === 'prompt' ? null : false)
  Object.assign(dialogState, { open: true, kind, opts, value: opts.value || '' })
  return new Promise((r) => (resolver = r))
}

export function confirmDialog(opts) {
  return show('confirm', opts)
}

export function promptDialog(opts) {
  return show('prompt', opts)
}

export function closeDialog(ok) {
  dialogState.open = false
  const r = resolver
  resolver = null
  if (dialogState.kind === 'prompt') r?.(ok ? dialogState.value.trim() : null)
  else r?.(!!ok)
}
