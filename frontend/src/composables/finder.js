import { onBeforeUnmount, ref } from 'vue'
import { api } from '../api'

// 搜索添加 / 长文识别共用：发起查找任务，轮询进度直到结束
export function useFinderJob() {
  const job = ref(null)
  const error = ref('')
  const starting = ref(false)
  let timer
  let fails = 0

  const busyOf = (j) => j && (j.status === 'running' || j.importing || (j.candidates || []).some((c) => c.state === 'resolving' || c.state === 'importing'))

  async function poll() {
    clearTimeout(timer)
    if (!job.value) return
    const id = job.value.id
    try {
      const j = await api(`/api/finder/${id}`)
      if (job.value?.id !== id) return
      job.value = j
      fails = 0
      error.value = ''
    } catch (e) {
      if (job.value?.id !== id) return
      // v3.3.25 偶尔一次网络失败（手机切到后台、信号不好）不再停止轮询：退避重试；找不到 / 没权限才停
      if ([401, 403, 404].includes(e.status) || ++fails > 20) {
        error.value = e.message
        return
      }
      timer = setTimeout(poll, Math.min(1200 * 2 ** fails, 15000))
      return
    }
    // 对应仓库中、或后台正在加入勾选的条目时继续轮询，列表原地更新
    if (busyOf(job.value)) timer = setTimeout(poll, 1200)
  }
  // 页面回到前台时，任务还在进行就立刻拉一次（后台时浏览器 / 小程序会暂停定时器）
  const onVisible = () => document.visibilityState === 'visible' && busyOf(job.value) && poll()
  if (typeof document !== 'undefined') document.addEventListener('visibilitychange', onVisible)

  async function start(path, body) {
    starting.value = true
    error.value = ''
    try {
      job.value = await api(path, { method: 'POST', body })
      poll()
    } catch (e) {
      error.value = e.message
    } finally {
      starting.value = false
    }
  }

  async function open(id) {
    job.value = { id }
    await poll()
  }

  // 列表里点了「加入」：接口立即返回最新任务，接着轮询看每一个的加入进度
  function adopt(j) {
    job.value = j
    poll()
  }

  function reset() {
    clearTimeout(timer)
    job.value = null
    error.value = ''
  }

  onBeforeUnmount(() => {
    clearTimeout(timer)
    if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', onVisible)
  })
  return { job, error, starting, start, poll, open, reset, adopt }
}
