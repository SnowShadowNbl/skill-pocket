import { reactive, watch } from 'vue'
import { api } from '../api'
import { track } from './analytics'
import { dock } from './dock'
import { toast } from './toast'

// AI 智能对比
// - 「对比模式」默认关闭，打开后卡片、GitHub 搜索结果、我提交的条目上出现对比勾选框；详情页随时可以「加入对比」。
// - 选中的条目存在浏览器里，跨页面、刷新后都保留；本站条目和 GitHub 上的仓库可以混在一起对比。
// - 开始对比后这组条目变成一条「对比记录」，在右下角的对比面板里看进度（像上传进度表），不用停在原页面等。
export const COMPARE_MAX = 6
const KEY = 'skp_compare'
const RUNS_KEY = 'skp_compare_runs'
const MODE_KEY = 'skp_compare_mode'
const RUNS_KEEP = 8

function readJson(store, key, fallback) {
  try {
    const v = JSON.parse(store.getItem(key) || 'null')
    return v ?? fallback
  } catch {
    return fallback
  }
}

function readMode() {
  try {
    return sessionStorage.getItem(MODE_KEY) === '1'
  } catch {
    return false
  }
}

export const compareState = reactive({
  list: (() => { const v = readJson(localStorage, KEY, []); return Array.isArray(v) ? v.slice(0, COMPARE_MAX) : [] })(),
  runs: (() => { const v = readJson(localStorage, RUNS_KEY, []); return Array.isArray(v) ? v.slice(0, RUNS_KEEP) : [] })(),
  mode: readMode(),
  open: false, // 对比面板是否展开
  starting: false,
})

/** 打开 / 关闭对比模式。关闭时保留已勾选的条目，下次打开还在 */
export function setCompareMode(on) {
  compareState.mode = !!on
  try {
    sessionStorage.setItem(MODE_KEY, on ? '1' : '0')
  } catch {}
  if (on) track('compare_mode', {})
}

// v3.3.22 手机上对比栏什么时候展开成长条（与小程序一致；电脑端始终是完整对比栏，不受影响）：
// ① 有勾选就显示长条（含页面打开时上次留下的勾选）；② 新勾选了卡片 → 展开；③ 打开 AI 智能对比开关 → 展开；
// ④ 用户点「最小化」后保持小圆按钮，开关开着也不自己弹出来；⑤ 收起后又勾选了新卡片 → 按 ② 重新展开
dock.compareMini = !compareState.list.length
watch(() => compareState.list.length, (n, old) => {
  if (n > old) dock.compareMini = false
})
watch(() => compareState.mode, (on) => {
  if (on) dock.compareMini = false
})

watch(() => compareState.list, (v) => { try { localStorage.setItem(KEY, JSON.stringify(v)) } catch {} }, { deep: true })
watch(() => compareState.runs, (v) => { try { localStorage.setItem(RUNS_KEY, JSON.stringify(v)) } catch {} }, { deep: true })
// 别的标签页改了对比栏，这里同步过来
addEventListener('storage', (e) => {
  if (e.key === KEY) compareState.list = readJson(localStorage, KEY, [])
  if (e.key === RUNS_KEY) compareState.runs = readJson(localStorage, RUNS_KEY, [])
})

const catName = (c) => (typeof c === 'string' ? c : c?.name || '')

/** 本站条目 → 对比栏里的一项（带上面板里展示的介绍、分类、星标） */
export function fromItem(it) {
  return {
    key: `i:${it.id}`, item_id: it.id, name: it.name, cover_url: it.cover_url || '', stars: it.stars ?? null,
    summary: it.summary || '', category: catName(it.category), kind: it.kind?.name || '', repo: it.repo_full_name || '',
  }
}

/** 外站仓库（GitHub 搜索结果）→ 对比栏里的一项；其实已收录的按本站条目算 */
export function fromCandidate(c) {
  const sub = c.sub_path || ''
  // 仓库标识（repo_id）一直带着：勾选后状态可能变（加入中 → 已收录），key 会从仓库变成条目号，靠它仍能认出是同一个
  const base = { name: c.name || c.full_name, cover_url: '', stars: c.stars ?? null, summary: c.description || c.summary || '', repo: c.full_name,
    repo_id: `${(c.full_name || '').toLowerCase()}/${sub}` }
  if (c.existing_item_id) return { ...base, key: `i:${c.existing_item_id}`, item_id: c.existing_item_id }
  return { ...base, key: `r:${c.full_name.toLowerCase()}/${sub}`, full_name: c.full_name, sub_path: sub, external: true }
}

/** v3.3.81 已经发起、还在进行中的对比里的条目：列表上显示转圈，不能再勾选 */
export function isComparing(entry) {
  return compareState.runs.some((r) => r.status === 'running' && (r.picked || []).some((x) => sameEntry(x, entry)))
}

/** 是不是同一个条目：key 相同，或条目号相同，或仓库 + 子目录相同（同仓库不同子目录的 Skill 不算） */
function sameEntry(a, b) {
  if (a.key === b.key) return true
  if (a.item_id && a.item_id === b.item_id) return true
  const ra = a.repo_id || (a.full_name ? `${a.full_name.toLowerCase()}/${a.sub_path || ''}` : '')
  const rb = b.repo_id || (b.full_name ? `${b.full_name.toLowerCase()}/${b.sub_path || ''}` : '')
  return !!ra && ra === rb
}

export function inCompare(entry) {
  return compareState.list.some((x) => x.key === entry.key)
}

export function toggleCompare(entry) {
  const i = compareState.list.findIndex((x) => x.key === entry.key)
  if (i >= 0) {
    compareState.list.splice(i, 1)
    return
  }
  if (compareState.list.length >= COMPARE_MAX) {
    toast(`最多同时对比 ${COMPARE_MAX} 个，先移除一些再加`, 'info')
    compareState.open = true
    return
  }
  compareState.list.push(entry)
  track('compare_add', { name: entry.name, external: !!entry.external })
}

export function removeCompare(key) {
  compareState.list = compareState.list.filter((x) => x.key !== key)
}

export function clearCompare() {
  compareState.list = []
}

export function compareEntries(list = compareState.list) {
  return list.map((x) => (x.item_id ? { item_id: x.item_id } : { full_name: x.full_name, sub_path: x.sub_path || '' }))
}

// ---------------------------------------------------------------- 对比记录（进度）

function upsertRun(r, picked) {
  const old = compareState.runs.find((x) => x.id === r.id)
  const row = {
    id: r.id, status: r.status, stage: r.stage || '', error: r.error || '',
    names: (r.subjects || []).map((s) => s.name), summary: r.result?.summary || '', created_at: r.created_at,
    picked: picked || old?.picked || [],
  }
  compareState.runs = [row, ...compareState.runs.filter((x) => x.id !== r.id)].slice(0, RUNS_KEEP)
  return row
}

/** 开始对比：选中的这组变成一条对比记录，对比栏清空，面板展开看进度。返回对比 id */
export async function startCompare() {
  const picked = compareState.list.slice()
  if (picked.length < 2 || compareState.starting) return null
  compareState.starting = true
  try {
    const r = await api('/api/compare', { method: 'POST', body: { entries: compareEntries(picked) } })
    track('compare', { count: picked.length })
    upsertRun(r, picked)
    compareState.list = []
    compareState.open = true
    pollRuns()
    return r.id
  } finally {
    compareState.starting = false
  }
}

/** 失败的对比再来一次：把当时选的条目放回对比栏后重新开始 */
export async function retryRun(run) {
  if (!run.picked?.length) return null
  compareState.list = run.picked.slice(0, COMPARE_MAX)
  compareState.runs = compareState.runs.filter((x) => x.id !== run.id)
  return startCompare()
}

export function dismissRun(id) {
  compareState.runs = compareState.runs.filter((x) => x.id !== id)
}

let pollTimer = null
/** 有进行中的对比时每 2.5 秒刷新一次进度；完成时提示一下 */
export function pollRuns() {
  clearTimeout(pollTimer)
  const running = compareState.runs.filter((x) => x.status === 'running')
  if (!running.length) return
  pollTimer = setTimeout(async () => {
    await Promise.all(running.map(async (x) => {
      try {
        const r = await api(`/api/compare/${x.id}`)
        upsertRun(r)
        if (r.status === 'done') toast(`对比完成：${x.names.join('、')}`, 'success')
        else if (r.status === 'failed') toast(`对比失败：${r.error || '请稍后再试'}`, 'error')
      } catch {}
    }))
    pollRuns()
  }, 2500)
}
pollRuns()
