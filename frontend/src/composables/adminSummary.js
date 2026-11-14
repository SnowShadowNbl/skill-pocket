import { reactive, watch } from 'vue'
import { api } from '../api'
import { authState, isAdminUser } from './auth'

// 管理员待处理的事：待审核 + 新反馈（实时动态只是信息，不算待办）。管理员登录时每 20 秒刷新一次
export const adminSummary = reactive({ data: null })
let timer

export async function refreshAdminSummary() {
  clearTimeout(timer)
  if (!isAdminUser()) {
    adminSummary.data = null
    return
  }
  try {
    adminSummary.data = await api('/api/admin/summary')
  } catch {}
  timer = setTimeout(refreshAdminSummary, document.visibilityState === 'hidden' ? 60000 : 20000)
}

export function adminBadge() {
  const d = adminSummary.data
  return d ? d.pending_reviews + d.feedback_new : 0
}

watch(() => authState.user?.role, refreshAdminSummary)
