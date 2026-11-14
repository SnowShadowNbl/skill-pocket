import { reactive } from 'vue'
import { authState } from './auth'

// 全局任务进度：右下角浮窗用。任意接口返回 task_id 时会立即刷新一次（见 api.js）
export const taskState = reactive({ tasks: [], pending: [], dismissed: new Set(loadDismissed()) })

// 「加入」等操作提交后、后台任务还没建好之前，先在任务浮窗里放一条占位，让人知道已经在处理了
let pendingSeq = 0
export function addPending(title, message) {
  const id = `pending-${++pendingSeq}`
  taskState.pending.unshift({ id, pending: true, status: 'running', kind_label: '加入', title, message, total: 0, done: 0, failed: 0, items: [], source: 'manual' })
  return id
}
export function removePending(id) {
  taskState.pending = taskState.pending.filter((t) => t.id !== id)
}

let timer
let busy = false

function loadDismissed() {
  try {
    return JSON.parse(sessionStorage.getItem('skillhub.dismissedTasks') || '[]')
  } catch {
    return []
  }
}

export function dismissTask(id) {
  taskState.dismissed.add(id)
  try {
    sessionStorage.setItem('skillhub.dismissedTasks', JSON.stringify([...taskState.dismissed]))
  } catch {}
}

export async function refreshTasks() {
  if (busy) return
  busy = true
  clearTimeout(timer)
  try {
    // 只显示自己的任务（管理员看全部）；未登录没有任务
    if (!authState.token) taskState.tasks = []
    else {
      const res = await fetch('/api/tasks/active', { headers: { authorization: `Bearer ${authState.token}` } })
      if (res.ok) taskState.tasks = await res.json()
    }
  } catch {
  } finally {
    busy = false
  }
  const running = taskState.tasks.some((t) => t.status === 'running')
  // 有任务在跑时 2 秒刷新；空闲时 15 秒（捕捉夜间采集等系统任务）
  timer = setTimeout(refreshTasks, document.visibilityState === 'hidden' ? 30000 : running ? 2000 : 15000)
}

export function bumpTasks() {
  setTimeout(refreshTasks, 300)
}
