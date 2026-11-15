import { reactive } from 'vue'
import { isQuotaEcho } from './quota'

export const toasts = reactive([])
let seq = 0

export function toast(message, type = 'info', ms = 2600) {
  if (isQuotaEcho(message)) return
  const id = ++seq
  toasts.push({ id, message, type })
  setTimeout(() => {
    const i = toasts.findIndex((t) => t.id === id)
    if (i >= 0) toasts.splice(i, 1)
  }, ms)
}
