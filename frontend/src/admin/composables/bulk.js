import { api } from '../../api'

// 批量执行：后端统一接口 POST /api/admin/<资源>/bulk，body { action, ids | filter + exclude + total, reason, params }
// 返回 { results: [{ id, label, ok, code, message }], ok_count, fail_count }；条数太多时返回 { task_id }（转后台任务）
export function runBulk(endpoint, { action, scope, reason = '', params }) {
  const body = { action, reason, params }
  if (scope.ids) body.ids = scope.ids
  else Object.assign(body, { filter: scope.filter, exclude: scope.exclude, total: scope.total })
  return api(endpoint, { method: 'POST', body })
}

// 后端还没有批量接口时：前端逐条调用单条接口（同时最多 4 条），把每条的结果收集成同样的格式
export async function runEach(items, fn, { concurrency = 4 } = {}) {
  const results = new Array(items.length)
  let next = 0
  const worker = async () => {
    while (next < items.length) {
      const i = next++
      const it = items[i]
      try {
        await fn(it)
        results[i] = { id: it.id, label: it.label, ok: true }
      } catch (e) {
        results[i] = { id: it.id, label: it.label, ok: false, code: e.code, message: e.message }
      }
    }
  }
  await Promise.all(Array.from({ length: Math.min(concurrency, items.length) }, worker))
  return results
}

// 重试后把新结果按 id 合并回原列表
export function mergeResults(old, fresh) {
  const map = new Map(fresh.map((r) => [r.id, r]))
  return old.map((r) => map.get(r.id) || r)
}
