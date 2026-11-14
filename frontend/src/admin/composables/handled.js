import { isCancelled } from '../../api'
import { toast } from '../../composables/toast'

// 处置类操作失败时的统一处理：两个管理员同时处理同一条，后提交的会收到 409 already_handled，
// 这时提示「已被 X 处理」并刷新这一条，不当成普通错误。
//   try { await api(...) } catch (e) { await onActionError(e, reload) }
export async function onActionError(e, reload) {
  if (isCancelled(e)) return
  if (e?.code === 'already_handled') {
    toast(e.message || '已被其他管理员处理', 'info')
    await reload?.()
    return
  }
  toast(e?.message || '操作失败', 'error')
}
