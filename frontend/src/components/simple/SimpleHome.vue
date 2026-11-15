<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { api, authHeaders, formatStars, isCancelled } from '../../api'
import { authState, requireLogin } from '../../composables/auth'
import { homeSignal } from '../../composables/collect'
import { compareState, fromCandidate, fromItem, inCompare, isComparing, toggleCompare } from '../../composables/compare'
import { homeMode, simpleUi } from '../../composables/homeMode'
import { useItemLink } from '../../composables/itemLink'
import { WECHAT_BIND_REQUIRED, isQuotaCode, showQuotaExhausted, waitForBind } from '../../composables/quota'
import { clearSearchHistory, forgetSearch, rememberSearch, searchHistory } from '../../composables/searchHistory'
import { addPending, bumpTasks, removePending } from '../../composables/tasks'
import { toast } from '../../composables/toast'
import CheckBox from '../CheckBox.vue'
import CompareModeToggle from '../CompareModeToggle.vue'
import ErrorNote from '../ErrorNote.vue'
import Icon from '../Icon.vue'
import ItemCard from '../ItemCard.vue'
import JoinBar from '../JoinBar.vue'
import GhFlow from './GhFlow.vue'

// v3.3.96 网页简洁模式（与小程序同一套逻辑）：一个搜索框，提交后上移到顶部，同一次查询左列本站、右列 GitHub（排除本站已收录）。
// - 电脑：左列本站用带封面图的卡片（ItemCard 网格），右列 GitHub 紧凑卡片 + 工作流动画，右列贴顶独立滚动
// - 手机：与小程序一致，左右两列紧凑卡片
// 两列合计勾 2~6 个发起智能对比；不在对比模式时右列多选「加入本站」，加入成功的条目从右列移到左列。
// 图片搜索：搜索框里的相机、粘贴 / 拖入图片、手机底栏 ＋，截图识别结果直接分列（已收录 → 左，可加入 → 右）
const itemLink = useItemLink()
const router = useRouter()
const props = defineProps({ active: { type: Boolean, default: true } }) // 首页在前台、且是简洁模式

const phase = ref('idle') // idle：搜索框在上方、下面插画；results：搜索框在顶部，下面两列
const draft = ref('')
const source = ref('text') // text / image
const query = ref('')
const focused = ref(false)
const ta = ref(null)
const boxEl = ref(null)
const fileInput = ref(null)
const dragging = ref(false)
let runId = 0

// ---------------------------------------------------------------- 输入框：多行自动长高（1~4 行），回车搜索，Shift+回车换行
const LINE = 24
const lines = ref(1)
function fit() {
  const el = ta.value
  if (!el) return
  el.style.height = 'auto'
  const n = Math.max(1, Math.min(4, Math.round((el.scrollHeight - 8) / LINE)))
  lines.value = n
  el.style.height = `${n * LINE + 8}px`
}
function setText(t) {
  draft.value = t
  nextTick(fit)
}
function onKey(e) {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault()
    submit(draft.value)
  } else if (e.key === 'Escape') focused.value = false
}

// ---------------------------------------------------------------- 联想面板
const hot = ref([])
const sugg = ref([])
let suggTimer
let suggSeq = 0
const REPO = /^(https?:\/\/)?(www\.)?github\.com\/[\w.-]+\/[\w.-]+|^[\w.-]+\/[\w.-]+$/i
const draftT = computed(() => draft.value.trim())
const isRepo = computed(() => !/\s/.test(draftT.value) && REPO.test(draftT.value))
const isLong = computed(() => draftT.value.length > 24 || draft.value.includes('\n'))
const panelMode = computed(() => (!draftT.value ? 'empty' : isRepo.value ? 'repo' : isLong.value ? 'long' : 'short'))
const showPanel = computed(() => focused.value && (panelMode.value !== 'empty' || searchHistory.value.length || hot.value.length))
api('/api/search/hot').then((r) => (hot.value = Array.isArray(r) ? r : [])).catch(() => {})

watch(draft, (v) => {
  nextTick(fit)
  clearTimeout(suggTimer)
  const t = v.trim()
  if (!t || isRepo.value || isLong.value) return (sugg.value = [])
  const my = ++suggSeq
  suggTimer = setTimeout(async () => {
    try {
      const r = await api(`/api/search/suggest?q=${encodeURIComponent(t)}`)
      if (my === suggSeq) sugg.value = Array.isArray(r) ? r.slice(0, 6) : []
    } catch {}
  }, 150)
})
function parts(name) {
  const q = draftT.value
  const i = q ? name.toLowerCase().indexOf(q.toLowerCase()) : -1
  return i < 0 ? [name, '', ''] : [name.slice(0, i), name.slice(i, i + q.length), name.slice(i + q.length)]
}
const firstLine = (s) => String(s).split(/\r?\n/)[0]
function onBlur() {
  setTimeout(() => (focused.value = false), 160) // 先让面板里的点击生效再收起
}
function pickText(t) {
  setText(t)
  submit(t)
}

// ---------------------------------------------------------------- 上移动画（FLIP：记下原位置，切到结果布局后从原位置滑过去）
const moving = ref(false)
async function toTop() {
  if (phase.value === 'results') return
  const before = boxEl.value?.getBoundingClientRect().top ?? 0
  phase.value = 'results'
  simpleUi.results = true
  await nextTick()
  const el = boxEl.value
  if (!el) return
  const dy = before - el.getBoundingClientRect().top
  if (!dy || matchMedia('(prefers-reduced-motion: reduce)').matches) return
  el.style.transition = 'none'
  el.style.transform = `translateY(${dy}px)`
  el.getBoundingClientRect()
  moving.value = true
  el.style.transition = 'transform 0.55s cubic-bezier(0.2, 0.8, 0.2, 1)'
  el.style.transform = ''
  setTimeout(() => {
    moving.value = false
    el.style.transition = ''
  }, 600)
}

// ---------------------------------------------------------------- 左列：本站
const site = reactive({ state: 'idle', items: [], error: '', refining: false, understanding: '', refined: false })
async function runSite(text, run) {
  Object.assign(site, { state: 'loading', items: [], error: '', understanding: '', refined: false })
  const q = text.slice(0, 200)
  const qs = (o) => new URLSearchParams(o).toString()
  try {
    let r = await api(`/api/search?${qs({ q })}`)
    if (run !== runId) return
    if (r.mode !== 'semantic') r = await api(`/api/items?${qs({ q, size: 30 })}`)
    if (run !== runId) return
    site.items = (r.items || []).slice(0, 30)
    site.understanding = r.understanding || ''
    site.refined = !r.ai_pending && !!r.understanding
    site.state = 'done'
    if (r.ai_pending) {
      site.refining = true
      try {
        const r2 = await api(`/api/search?${qs({ q, stage: 'ai' })}`)
        if (run === runId && r2.mode === 'semantic' && r2.items) {
          site.items = r2.items.slice(0, 30)
          site.understanding = r2.understanding || ''
          site.refined = true
        }
      } catch {}
      if (run === runId) site.refining = false
    }
  } catch (e) {
    if (run !== runId) return
    site.state = 'error'
    site.error = e.message || '加载失败'
  }
}

// ---------------------------------------------------------------- 右列：GitHub 功能搜索
const gh = reactive({ state: 'idle', job: null, error: '', code: '' })
let jobTimer
let jobFails = 0
const jobBusy = (j) => j && (j.status === 'running' || j.importing || (j.candidates || []).some((c) => c.state === 'resolving' || c.state === 'importing'))
async function pollJob(id, run) {
  clearTimeout(jobTimer)
  try {
    const j = await api(`/api/finder/${id}`)
    if (run !== runId) return
    gh.job = j
    jobFails = 0
    if (j.status === 'failed') return Object.assign(gh, { state: 'error', error: j.error || j.message || '搜索失败' })
  } catch (e) {
    if (run !== runId) return
    if ([401, 403, 404].includes(e.status) || ++jobFails > 20) return Object.assign(gh, { state: 'error', error: e.message || '搜索失败' })
    jobTimer = setTimeout(() => pollJob(id, run), Math.min(1200 * 2 ** jobFails, 15000))
    return
  }
  if (jobBusy(gh.job)) jobTimer = setTimeout(() => pollJob(id, run), 1200)
  else gh.state = 'done'
}
async function runGithub(text, run) {
  clearTimeout(jobTimer)
  Object.assign(gh, { job: null, error: '', code: '' })
  if (!authState.user) return (gh.state = 'guest')
  gh.state = 'loading'
  try {
    // 自动触发：额度用完 / 需要绑定微信时不弹窗，在右列原位提示
    const j = await api('/api/finder/search', { method: 'POST', body: { q: text.slice(0, 300) }, quietQuota: true })
    if (run !== runId) return
    gh.job = j
    pollJob(j.id, run)
  } catch (e) {
    if (run !== runId) return
    if (isCancelled(e)) return (gh.state = 'guest')
    Object.assign(gh, { state: 'error', error: e.message || '搜索失败', code: e.code || '' })
  }
}
async function loginForGithub() {
  if (!(await requireLogin('登录后同时搜 GitHub'))) return
  if (query.value && source.value === 'text') runGithub(query.value, runId)
}
const onVisible = () => document.visibilityState === 'visible' && gh.job && jobBusy(gh.job) && pollJob(gh.job.id, runId)
document.addEventListener('visibilitychange', onVisible)

// ---------------------------------------------------------------- 图片搜索：截图识别结果直接分列
const shot = reactive({ state: 'idle', id: null, items: [], error: '', code: '', preview: '' })
let shotTimer
let zhPolls = 0
let lastFile = null
async function pollShot(run) {
  clearTimeout(shotTimer)
  if (!shot.id) return
  try {
    const r = await api(`/api/uploads/${shot.id}`)
    if (run !== runId) return
    shot.items = r.items || []
  } catch {}
  if (run !== runId) return
  if (shot.items.some((x) => x.state === 'resolving')) return (shotTimer = setTimeout(() => pollShot(run), 1200))
  shot.state = shot.items.length ? 'done' : 'empty'
  // 中文简介在所有条目对应完后才批量翻译，晚几秒到：还没有 description_zh 字段就再拉几次（最多约 18 秒）
  const zhPending = shot.items.some((x) => x.match && x.match.full_name && !('description_zh' in x.match))
  if (zhPending && zhPolls++ < 12) shotTimer = setTimeout(() => pollShot(run), 1500)
}
async function runImage(file, rebound = false) {
  if (!file) return
  if (!(await requireLogin('图片搜索需要先登录'))) return
  if (!file.type.startsWith('image/')) return toast('请选择图片文件', 'error')
  if (file.size > 10 * 1024 * 1024) return toast('图片不能超过 10MB', 'error')
  lastFile = file
  const run = ++runId
  seen.clear()
  source.value = 'image'
  query.value = ''
  setText('')
  sel.value = new Set()
  Object.assign(site, { state: 'done', items: [], understanding: '', refined: false })
  Object.assign(gh, { state: 'idle', job: null })
  clearTimeout(jobTimer)
  if (shot.preview) URL.revokeObjectURL(shot.preview)
  Object.assign(shot, { state: 'uploading', id: null, items: [], error: '', code: '', preview: URL.createObjectURL(file) })
  zhPolls = 0
  toTop()
  try {
    const fd = new FormData()
    fd.append('file', file)
    const res = await fetch('/api/uploads', { method: 'POST', body: fd, headers: authHeaders() })
    const data = await res.json().catch(() => ({}))
    if (run !== runId) return
    if (!res.ok) {
      const d = data.detail
      const code = (d && d.code) || ''
      const msg = (d && typeof d === 'object' ? d.message : d) || `识别失败（${res.status}）`
      if (code === WECHAT_BIND_REQUIRED && !rebound) {
        if (await waitForBind(msg)) return runImage(file, true) // 绑定好后自动重新识别这张图
      } else if (isQuotaCode(code)) showQuotaExhausted(msg, code)
      shot.code = code
      throw new Error(msg)
    }
    shot.id = data.id
    shot.items = data.items || []
    shot.state = 'resolving'
    pollShot(run)
  } catch (e) {
    if (run !== runId) return
    shot.state = 'error'
    shot.error = e.message || '上传失败，请检查网络后重试'
  }
}
function pickImage() {
  fileInput.value?.click()
}
function onFile(e) {
  const f = e.target.files?.[0]
  e.target.value = ''
  if (f) runImage(f)
}
function onPaste(e) {
  const f = [...(e.clipboardData?.files || [])].find((x) => x.type.startsWith('image/'))
  if (f) {
    e.preventDefault()
    runImage(f)
  }
}
function onDrop(e) {
  dragging.value = false
  const f = [...(e.dataTransfer?.files || [])].find((x) => x.type.startsWith('image/'))
  if (f) runImage(f)
}
// 手机底栏 ＋ →「扫描识别图片」
watch(() => homeSignal.simpleImage, () => nextTick(pickImage))

// ---------------------------------------------------------------- 提交
function submit(text) {
  const q = (text || '').trim()
  if (!q) return
  focused.value = false
  ta.value?.blur()
  rememberSearch(q)
  const run = ++runId
  seen.clear()
  source.value = 'text'
  query.value = q
  sel.value = new Set()
  shot.state = 'idle'
  clearTimeout(shotTimer)
  toTop()
  runSite(q, run)
  runGithub(q, run)
}
const retrySite = () => runSite(query.value, runId)
const retryGithub = () => (source.value === 'image' ? (lastFile ? runImage(lastFile, true) : pickImage()) : runGithub(query.value, runId))

// ---------------------------------------------------------------- 两列数据
const repoKey = (fn, sub) => `${(fn || '').toLowerCase()}/${sub || ''}`
const ghSource = computed(() => {
  if (source.value === 'image') {
    return shot.items
      .map((it, i) => ({ it, i }))
      .filter(({ it }) => it.match && it.match.full_name)
      .map(({ it, i }) => ({
        i, name: it.name, zh: it.match.description_zh || '', summary: it.match.description || it.description || '', full_name: it.match.full_name,
        sub_path: it.sub_path || '', state: it.state, existing_item_id: it.existing_item_id || null, stars: it.match.stars ?? null, kind: it.kind || '',
      }))
  }
  return ((gh.job && gh.job.candidates) || [])
    .map((c, i) => ({ c, i }))
    .filter(({ c }) => c.full_name || (c.match && c.match.full_name))
    .map(({ c, i }) => ({
      i, name: c.name || c.full_name, zh: c.description_zh || c.match?.description_zh || '',
      summary: c.description || c.match?.description || c.reason || '', full_name: c.full_name || c.match.full_name, sub_path: c.sub_path || '',
      state: c.state, existing_item_id: c.existing_item_id || null, stars: c.stars ?? c.match?.stars ?? null, kind: c.kind || '',
    }))
})
const right = computed(() => {
  const seenK = new Set()
  const out = []
  for (const x of ghSource.value) {
    if (!['matched', 'importing'].includes(x.state)) continue
    const k = repoKey(x.full_name, x.sub_path)
    if (seenK.has(k)) continue
    seenK.add(k)
    out.push({ ...x, key: k })
  }
  return out
})
const excluded = computed(() => ghSource.value.filter((x) => x.state === 'existing').length)
// 右侧识别出、本站已收录但左列还没有的条目：取完整条目（电脑上要显示封面卡片）
const itemFull = reactive({})
const asked = new Set()
async function loadItem(id) {
  if (asked.has(id)) return
  asked.add(id)
  try {
    const it = await api(`/api/items/${id}`)
    if (it && it.id) itemFull[id] = it
  } catch {
    asked.delete(id)
  }
}
const left = computed(() => {
  const out = site.items.map((it) => ({ key: `i:${it.id}`, id: it.id, name: it.name, summary: it.summary || '', reason: it.match?.reason || '', item: it }))
  const have = new Set(site.items.map((x) => x.id))
  for (const x of ghSource.value) {
    if (x.state !== 'existing' || !x.existing_item_id || have.has(x.existing_item_id)) continue
    have.add(x.existing_item_id)
    const full = itemFull[x.existing_item_id]
    out.push({ key: `i:${x.existing_item_id}`, id: x.existing_item_id, name: full?.name || x.name, summary: full?.summary || x.zh || x.summary, reason: '', item: full || null, fromGh: true, gh: x })
  }
  return out
})
watch(
  () => left.value.filter((x) => x.fromGh && !x.item).map((x) => x.id).join(','),
  (ids) => ids && ids.split(',').slice(0, 20).forEach((id) => loadItem(+id)),
)
// 只有新出现的卡片播入场动画（从 GitHub 并过来的从右边飞入）
const seen = new Set()
const enterOf = reactive({})
watch(
  () => [...left.value.map((x) => x.key), ...right.value.map((x) => x.key)].join('|'),
  () => {
    let n = 0
    for (const x of [...left.value, ...right.value]) {
      if (seen.has(x.key)) continue
      seen.add(x.key)
      enterOf[x.key] = { cls: x.fromGh ? 'sh-fly' : 'sh-in', delay: `${Math.min(n++, 8) * 45}ms` }
    }
  },
)

// ---------------------------------------------------------------- 工作流节点
const flowDoneShown = ref(false)
watch(
  () => [gh.state, shot.state],
  ([g, s]) => {
    flowDoneShown.value = false
    if (g === 'done' || s === 'done') setTimeout(() => (flowDoneShown.value = true), 700)
  },
)
const flow = computed(() => {
  if (source.value === 'image') {
    const s = shot.state
    const active = s === 'uploading' ? 1 : s === 'resolving' ? 2 : s === 'done' || s === 'empty' ? 3 : 0
    const names = shot.items.map((x) => x.name).filter(Boolean).slice(0, 8)
    const resolved = shot.items.filter((x) => x.state !== 'resolving').length
    return { nodes: ['上传', '识别', '对应仓库', '排除本站'], active, keywords: names, group: s === 'resolving' ? resolved + 1 : s === 'done' ? names.length + 1 : 0 }
  }
  const j = gh.job
  const st = (j && j.stage) || 'start'
  let active = { start: 0, plan: 0, fetch: 0, read: 0, search: 1, resolve: 2, rank: 2, done: 3 }[st] ?? 0
  if (gh.state === 'done') active = 3
  const keywords = (j && j.plan && j.plan.queries) || []
  const m = j && j.message && /第\s*(\d+)\s*\/\s*(\d+)\s*组/.exec(j.message)
  const group = st === 'search' ? (m ? +m[1] : 1) : active >= 2 ? keywords.length + 1 : 0
  return { nodes: ['理解需求', '搜索', '排序', '排除本站'], active, keywords, group }
})
const flowSummary = computed(() => {
  const done = source.value === 'image' ? ['done', 'empty'].includes(shot.state) : gh.state === 'done'
  return done && flowDoneShown.value ? `找到 ${right.value.length} 个 · 已排除本站 ${excluded.value} 个` : ''
})
const imgWaiting = computed(() => source.value === 'image' && ['uploading', 'resolving'].includes(shot.state))
const ghLoading = computed(() => (source.value === 'image' ? imgWaiting.value && !right.value.length : gh.state === 'loading' && !right.value.length))
// 右列错误：额度 / 绑定类走 ErrorNote（带按钮），其他错误显示在工作流下面
const ghErr = computed(() => (source.value === 'image' ? (shot.state === 'error' ? { msg: shot.error, code: shot.code } : null) : gh.state === 'error' ? { msg: gh.error, code: gh.code } : null))
const leftLoading = computed(() => (source.value === 'text' ? site.state === 'loading' : imgWaiting.value && !left.value.length))
const leftEmpty = computed(() => !leftLoading.value && !left.value.length && (source.value === 'image' ? ['done', 'empty', 'error'].includes(shot.state) : site.state === 'done'))
const rightEmpty = computed(() => !right.value.length && (source.value === 'image' ? ['done', 'empty'].includes(shot.state) : gh.state === 'done'))

// ---------------------------------------------------------------- 对比与加入
const compareOn = computed(() => compareState.mode)
const sel = ref(new Set())
const leftEntry = (x) => (x.item ? fromItem(x.item) : { key: x.key, item_id: x.id, name: x.name, summary: x.summary, cover_url: '', stars: null, repo: x.gh ? x.gh.full_name : '' })
const rightEntry = (x) => fromCandidate({ name: x.name, full_name: x.full_name, sub_path: x.sub_path, existing_item_id: null, stars: x.stars, description: x.zh || x.summary })
const COMPARING_TIP = '正在对比中，完成后可在对比栏查看结果'
const JOINING_TIP = '正在加入本站，加好后会变成「已收录」'
// 与小程序 tapLeft 一致：不在对比模式时打开详情；对比模式下勾选 / 取消，正在对比的提示
function tapLeft(x) {
  if (!compareOn.value) return router.push(itemLink(x.id))
  const e = leftEntry(x)
  if (isComparing(e)) return toast(COMPARING_TIP, 'info', 2600)
  toggleCompare(e)
}
/** 电脑上的封面卡片：对比模式下点卡片任何位置都是勾选（不打开详情），和小程序一致 */
function onLeftCard(e, x) {
  if (!compareOn.value) return
  e.preventDefault()
  e.stopPropagation()
  tapLeft(x)
}
function tapRight(x) {
  if (compareOn.value) {
    const e = rightEntry(x)
    if (isComparing(e)) return toast(COMPARING_TIP, 'info', 2600)
    return toggleCompare(e)
  }
  if (x.state === 'importing') return toast(JOINING_TIP, 'info', 2600)
  const s = new Set(sel.value)
  s.has(x.key) ? s.delete(x.key) : s.add(x.key)
  sel.value = s
}
const picked = computed(() => right.value.filter((x) => sel.value.has(x.key) && x.state === 'matched'))
const importingN = computed(() => right.value.filter((x) => x.state === 'importing').length)

const joining = ref(false)
const joinBatches = ref([])
function settleShot(resolved) {
  const ids = new Map((resolved || []).map((r) => [repoKey(r.full_name, r.sub_path), r.item_id]))
  shot.items.forEach((it) => {
    if (it.state !== 'importing' || !it.match) return
    const id = ids.get(repoKey(it.match.full_name, it.sub_path))
    Object.assign(it, id ? { state: 'existing', existing_item_id: id } : { state: 'matched' })
  })
}
async function waitShotImport(id) {
  const until = Date.now() + 15 * 60 * 1000
  while (Date.now() < until) {
    await new Promise((r) => setTimeout(r, 2000))
    try {
      const r = await api(`/api/uploads/${id}`)
      if (r.status !== 'importing' && r.import) return r.import
    } catch (e) {
      if ([401, 403, 404].includes(e.status)) throw e
    }
  }
  throw new Error('加入时间较长，稍后可在「我的 → 我提交的」里查看结果')
}
async function doJoin() {
  const list = picked.value
  if (!list.length || joining.value) return
  if (!(await requireLogin('登录后就可以加入本站'))) return
  joining.value = true
  const keys = list.map((x) => x.key)
  sel.value = new Set([...sel.value].filter((k) => !keys.includes(k)))
  const pid = addPending(`加入 ${list.length} 个条目`, `正在加入 ${list.length} 个，准备分析…`)
  const run = runId
  try {
    if (source.value === 'image') {
      list.forEach((x) => shot.items[x.i] && (shot.items[x.i].state = 'importing'))
      const picks = list.map((x) => ({ full_name: x.full_name, name: x.name, sub_path: x.sub_path || null }))
      let data = await api(`/api/uploads/${shot.id}/import`, { method: 'POST', body: { picks } })
      if (data.queued) {
        toast(`正在加入 ${list.length} 个，加好后会提示你`, 'info', 3000)
        data = await waitShotImport(shot.id)
      }
      if (run === runId) settleShot(data.resolved)
      ;(data.errors || []).forEach((m) => toast(m, 'error', 4000))
      if ((data.created || []).length) toast(`已加入 ${data.created.length} 个条目，正在后台整理`, 'success', 3500)
      removePending(pid)
    } else {
      const cands = gh.job.candidates
      list.forEach((x) => cands[x.i] && (cands[x.i].state = 'importing'))
      const picks = list.map((x) => ({ full_name: x.full_name, name: x.name, sub_path: x.sub_path || null, kind: x.kind || '', index: x.i }))
      const r = await api(`/api/finder/${gh.job.id}/import`, { method: 'POST', body: { picks } })
      if (run === runId && r.job) {
        gh.job = r.job
        pollJob(r.job.id, run)
      }
      joinBatches.value = [...joinBatches.value, { keys, pid, run }]
    }
  } catch (e) {
    removePending(pid)
    if (source.value === 'image') shot.items.forEach((it) => it.state === 'importing' && (it.state = 'matched'))
    else (gh.job?.candidates || []).forEach((c, i) => list.some((x) => x.i === i) && c.state === 'importing' && (c.state = 'matched'))
    sel.value = new Set([...sel.value, ...keys])
    if (!isCancelled(e)) toast(e.message || '加入失败，请重试', 'error', 4000)
  } finally {
    bumpTasks()
    joining.value = false
  }
}
watch(
  () => ghSource.value.map((x) => x.state).join(),
  () => {
    if (source.value !== 'text' || !joinBatches.value.length) return
    const states = new Map(ghSource.value.map((x) => [repoKey(x.full_name, x.sub_path), x.state]))
    const done = joinBatches.value.filter((b) => b.run !== runId || !b.keys.some((k) => states.get(k) === 'importing'))
    if (!done.length) return
    joinBatches.value = joinBatches.value.filter((b) => !done.includes(b))
    done.forEach((b) => {
      removePending(b.pid)
      const ok = b.keys.filter((k) => states.get(k) === 'existing').length
      if (ok) toast(`已加入 ${ok} 个，正在后台整理`, 'success', 3500)
    })
    bumpTasks()
  },
)

// ---------------------------------------------------------------- 插画里的小物件：点一下转一圈 / 晃一晃 / 跳一跳
const pk = reactive({})
const pkTimer = {}
function poke(k) {
  pk[k] = false
  clearTimeout(pkTimer[k])
  requestAnimationFrame(() => {
    pk[k] = true
    pkTimer[k] = setTimeout(() => (pk[k] = false), 900)
  })
}

function backToIdle() {
  runId++
  clearTimeout(jobTimer)
  clearTimeout(shotTimer)
  phase.value = 'idle'
  simpleUi.results = false
  setText('')
  sel.value = new Set()
}
watch(
  () => props.active,
  (v) => (simpleUi.results = v && phase.value === 'results'),
)
onMounted(() => nextTick(fit))
onBeforeUnmount(() => {
  clearTimeout(jobTimer)
  clearTimeout(shotTimer)
  document.removeEventListener('visibilitychange', onVisible)
  simpleUi.results = false
})
defineExpose({ pickImage })
const homeOn = computed(() => homeMode.value === 'simple')
// 手机窄屏：提示文字用短版，保持一行
const narrowMq = matchMedia('(max-width: 480px)')
const narrow = ref(narrowMq.matches)
narrowMq.addEventListener?.('change', (e) => (narrow.value = e.matches))
</script>

<template>
  <section class="sh relative" :class="phase === 'idle' ? 'sh-idle' : 'sh-res'" @dragover.prevent="dragging = true" @dragleave.self="dragging = false" @drop.prevent="onDrop">
    <!-- 背景：页头同款网格与光晕 -->
    <div class="pointer-events-none absolute inset-0 overflow-hidden">
      <div class="hero-grid" />
      <span class="hero-glow -top-[220px] -right-[120px] h-[420px] w-[420px] bg-[rgb(90_162_255/0.30)]" />
      <span class="hero-glow -top-10 -left-40 h-[300px] w-[300px] bg-[rgb(30_86_214/0.12)] [animation-delay:-8s] [animation-duration:26s]" />
    </div>

    <div class="relative mx-auto px-4 md:px-6" :class="phase === 'idle' ? 'max-w-[760px] pt-8 md:pt-[9vh]' : 'max-w-[1440px] pt-4 md:pt-5'">
      <!-- 抬头：搜索前居中显示，搜索后收起 -->
      <Transition name="sh-title">
        <div v-if="phase === 'idle'" class="mb-5 text-center md:mb-7">
          <h1 class="m-0 text-[26px] leading-9 font-semibold tracking-[-0.025em] md:text-[38px] md:leading-[48px]">一起探索 <em class="text-gradient not-italic">开源世界</em></h1>
        </div>
      </Transition>

      <!-- 搜索框 -->
      <div ref="boxEl" class="relative z-30" :class="phase === 'idle' ? '' : 'mx-auto max-w-[920px]'">
        <form class="sh-box flex items-center gap-2 rounded-[14px] border bg-white py-[6px] pr-[6px] pl-3.5" :class="[focused ? 'is-focus' : '', dragging ? 'is-drag' : '']" role="search" @submit.prevent="submit(draft)">
          <Icon name="search" :size="19" class="shrink-0 self-center text-mute" />
          <textarea
            ref="ta"
            v-model="draft"
            rows="1"
            maxlength="2000"
            enterkeyhint="search"
            class="min-w-0 flex-1 resize-none self-center bg-transparent py-1 text-[16px] leading-6 text-ink outline-none placeholder:text-mute md:text-[15.5px]"
            :placeholder="narrow ? '描述想找的 Skill' : '描述你想找的 Skill 或模型'"
            aria-label="描述你想找的 Skill 或模型"
            @keydown="onKey"
            @focus="focused = true"
            @blur="onBlur"
            @paste="onPaste"
          />
          <button v-if="draft" type="button" class="grid h-8 w-8 shrink-0 cursor-pointer place-items-center self-center rounded-full text-mute hover:text-ink" aria-label="清空" @click="setText(''); ta?.focus()">
            <span class="grid h-[18px] w-[18px] place-items-center rounded-full bg-ink/25 text-white"><Icon name="x" :size="12" /></span>
          </button>
          <button type="button" class="grid h-10 w-10 shrink-0 cursor-pointer place-items-center self-center rounded-[9px] text-ink-2 transition-colors hover:bg-hover hover:text-brand" title="上传或粘贴截图识别" aria-label="图片搜索" @click="pickImage"><Icon name="camera" :size="19" /></button>
          <button type="submit" class="btn-primary h-10 shrink-0 self-center px-4 sm:px-5" :disabled="!draftT">搜索</button>
          <input ref="fileInput" type="file" accept="image/*" class="hidden" @change="onFile" />
        </form>

        <!-- 联想面板 -->
        <Transition name="toast">
          <div v-if="showPanel" class="sh-panel glass-strong absolute inset-x-0 top-full z-40 mt-2 max-h-[min(420px,60vh)] overflow-y-auto rounded-[12px] p-2" @mousedown.prevent>
            <button v-if="panelMode === 'repo'" class="sh-row flex w-full cursor-pointer items-center gap-2.5 rounded-[8px] px-2.5 py-2.5 text-left hover:bg-hover" @click="pickText(draftT)">
              <Icon name="github" :size="15" class="shrink-0 text-brand" /><span class="min-w-0 flex-1 truncate text-[14px] font-medium">直接收录这个仓库</span>
            </button>
            <button v-else-if="panelMode === 'long'" class="sh-row flex w-full cursor-pointer items-center gap-2.5 rounded-[8px] px-2.5 py-2.5 text-left hover:bg-hover" @click="pickText(draft)">
              <Icon name="sparkles" :size="15" class="shrink-0 text-brand" /><span class="min-w-0 flex-1 truncate text-[14px]">按描述分析</span>
            </button>
            <template v-else-if="panelMode === 'short'">
              <RouterLink v-for="(s, i) in sugg" :key="s.id" :to="itemLink(s.id)" class="sh-row flex items-center gap-2.5 rounded-[8px] px-2.5 py-2 hover:bg-hover" :style="{ '--d': `${i * 30}ms` }" @click="focused = false">
                <Icon name="search" :size="14" class="shrink-0 text-mute" />
                <span class="min-w-0 flex-1">
                  <span class="block truncate text-[14px]">{{ parts(s.name)[0] }}<b class="font-semibold text-brand">{{ parts(s.name)[1] }}</b>{{ parts(s.name)[2] }}</span>
                  <span v-if="s.summary" class="block truncate text-[12px] text-mute">{{ s.summary }}</span>
                </span>
              </RouterLink>
              <button class="sh-row flex w-full cursor-pointer items-center gap-2.5 rounded-[8px] px-2.5 py-2 text-left hover:bg-hover" @click="pickText(draft)">
                <Icon name="arrow-right" :size="14" class="shrink-0 text-brand" /><span class="min-w-0 flex-1 truncate text-[13.5px] text-brand">搜索「{{ draftT }}」</span>
              </button>
            </template>
            <template v-else>
              <div v-if="searchHistory.length" class="px-1.5 pt-1 pb-1.5">
                <div class="mb-1 flex items-center"><span class="cap">最近搜索</span><button class="ml-auto cursor-pointer text-[12px] text-mute hover:text-brand" @click="clearSearchHistory">清空</button></div>
                <div v-for="(h, i) in searchHistory" :key="h" class="sh-row group flex items-center gap-2 rounded-[8px] px-1" :style="{ '--d': `${i * 25}ms` }">
                  <Icon name="clock" :size="13" class="shrink-0 text-mute" />
                  <button class="min-w-0 flex-1 cursor-pointer truncate py-1.5 text-left text-[13.5px] hover:text-brand" :title="h" @click="pickText(h)">{{ firstLine(h) }}</button>
                  <button class="grid h-7 w-7 shrink-0 cursor-pointer place-items-center rounded-full text-mute hover:bg-hover hover:text-ink" :aria-label="`删除 ${firstLine(h)}`" @click="forgetSearch(h)"><Icon name="x" :size="12" /></button>
                </div>
              </div>
              <div v-if="hot.length" class="px-1.5 pt-1 pb-1" :class="{ 'border-t border-line-2 pt-2': searchHistory.length }">
                <span class="cap mb-1 block">大家在搜</span>
                <div class="grid grid-cols-2 gap-x-3">
                  <button v-for="(h, i) in hot" :key="h.q" class="sh-row flex min-w-0 cursor-pointer items-center gap-2 rounded-[7px] px-1 py-1.5 text-left text-[13px] hover:bg-hover" :style="{ '--d': `${i * 30}ms` }" @click="pickText(h.q)">
                    <span class="w-4 shrink-0 text-center font-mono text-[12px] font-semibold" :class="i < 3 ? 'text-brand' : 'text-mute'">{{ i + 1 }}</span>
                    <span class="min-w-0 truncate">{{ h.q }}</span>
                  </button>
                </div>
              </div>
            </template>
          </div>
        </Transition>
      </div>

      <!-- 空态插画：口袋与漂浮卡片、玻璃小方块，点一下有回应；搜索后淡出 -->
      <div v-if="phase === 'idle'" class="sh-art relative mx-auto mt-6 h-[300px] max-w-[560px] md:mt-10 md:h-[320px]" aria-hidden="true">
        <img src="/simple/glow.svg" alt="" class="sh-breath pointer-events-none absolute inset-x-6 top-0 h-[190px] w-[calc(100%-48px)] object-cover" />
        <img src="/simple/orbit.svg" alt="" class="sh-spin pointer-events-none absolute top-3 left-1/2 -ml-[160px] h-[170px] w-[320px]" />
        <button class="sh-hit absolute bottom-[164px] left-1/2 -ml-[72px] h-[84px] w-[72px]" tabindex="-1" @click="poke('cardA')">
          <span class="sh-float block h-full w-full" style="--dur: 4.6s; --amp: -7px"><img src="/simple/card-a.svg" alt="" class="h-full w-full" :class="{ 'pk-flip': pk.cardA, 'pk-pop': pk.pocket }" /></span>
        </button>
        <button class="sh-hit absolute bottom-[170px] left-1/2 -ml-1 h-[84px] w-[72px]" tabindex="-1" @click="poke('cardB')">
          <span class="sh-float block h-full w-full" style="--dur: 5.2s; --amp: -9px; animation-delay: -1.4s"><img src="/simple/card-b.svg" alt="" class="h-full w-full" :class="{ 'pk-flip': pk.cardB, 'pk-pop pk-late': pk.pocket }" /></span>
        </button>
        <button class="sh-hit absolute bottom-[118px] left-1/2 -ml-[78px] h-[92px] w-[156px]" tabindex="-1" @click="poke('pocket')">
          <span class="sh-bob block h-full w-full"><img src="/simple/pocket.svg" alt="" class="h-full w-full" :class="{ 'pk-wobble': pk.pocket }" /></span>
        </button>
        <button class="sh-hit absolute top-10 left-[14%] h-12 w-12 p-1" tabindex="-1" @click="poke('search')">
          <span class="sh-float block h-full w-full" style="--dur: 3.8s; --amp: -6px; animation-delay: -0.6s"><img src="/simple/chip-search.svg" alt="" class="h-full w-full" :class="{ 'pk-spin': pk.search }" /></span>
        </button>
        <button class="sh-hit absolute top-4 right-[15%] h-11 w-11 p-1.5" tabindex="-1" @click="poke('spark')">
          <span class="sh-float block h-full w-full" style="--dur: 4.2s; --amp: -8px; animation-delay: -2s"><img src="/simple/chip-spark.svg" alt="" class="h-full w-full" :class="{ 'pk-burst': pk.spark }" /></span>
        </button>
        <button class="sh-hit absolute bottom-6 left-[16%] h-[58px] w-[68px]" tabindex="-1" @click="poke('t1')">
          <span class="sh-float block h-full w-full" style="--dur: 5.6s; --amp: -6px"><img src="/simple/tile-doc.svg" alt="" class="h-full w-full" :class="{ 'pk-hop': pk.t1 }" /></span>
        </button>
        <button class="sh-hit absolute bottom-0 left-1/2 -ml-[34px] h-[58px] w-[68px]" tabindex="-1" @click="poke('t2')">
          <span class="sh-float block h-full w-full" style="--dur: 6.2s; --amp: -7px; animation-delay: -2.2s"><img src="/simple/tile-code.svg" alt="" class="h-full w-full" :class="{ 'pk-hop': pk.t2 }" /></span>
        </button>
        <button class="sh-hit absolute right-[16%] bottom-8 h-[58px] w-[68px]" tabindex="-1" @click="poke('t3')">
          <span class="sh-float block h-full w-full" style="--dur: 5.9s; --amp: -6px; animation-delay: -3.6s"><img src="/simple/tile-cube.svg" alt="" class="h-full w-full" :class="{ 'pk-spin': pk.t3 }" /></span>
        </button>
        <img src="/simple/dot.svg" alt="" class="sh-twinkle pointer-events-none absolute bottom-[110px] left-[8%] h-3 w-3" style="--d: 0s" />
        <img src="/simple/dot.svg" alt="" class="sh-twinkle pointer-events-none absolute right-[9%] bottom-[150px] h-2 w-2" style="--d: -1.2s" />
        <img src="/simple/dot.svg" alt="" class="sh-twinkle pointer-events-none absolute bottom-[78px] left-[44%] h-2.5 w-2.5" style="--d: -2.1s" />
      </div>

      <!-- 结果 -->
      <div v-else class="sh-results mt-4 pb-10">
        <div class="mb-3 flex items-center gap-2">
          <button class="inline-flex cursor-pointer items-center gap-1 text-[13px] text-mute hover:text-brand" @click="backToIdle"><Icon name="arrow-left" :size="14" />重新开始</button>
          <button v-if="source === 'image' && shot.preview" class="h-8 w-8 shrink-0 cursor-pointer overflow-hidden rounded-md border border-line" title="换一张图片" @click="pickImage"><img :src="shot.preview" alt="当前图片" class="h-full w-full object-cover" /></button>
          <div class="ml-auto"><CompareModeToggle /></div>
        </div>

        <!-- 图片搜索：进度条整行放在两列上方 -->
        <div v-if="source === 'image'" class="sh-flowbar mb-3 rounded-[12px] px-3.5 py-3">
          <GhFlow :nodes="flow.nodes" :active="flow.active" :keywords="flow.keywords" :group="flow.group" :summary="flowSummary" :failed="ghErr && !isQuotaCode(ghErr.code) ? ghErr.msg : ''" />
          <ErrorNote v-if="ghErr && isQuotaCode(ghErr.code)" class="mt-2.5" :message="ghErr.msg" :code="ghErr.code" @retry="retryGithub" />
          <div v-else-if="ghErr" class="mt-2.5 grid grid-cols-2 gap-2 sm:flex">
            <button class="btn-primary btn-sm justify-center" @click="pickImage"><Icon name="refresh" :size="14" />重选图片</button>
            <button class="btn-glass btn-sm justify-center" @click="ta?.focus()">改用文字搜索</button>
          </div>
        </div>

        <div class="sh-grid grid grid-cols-2 items-start gap-2.5 lg:grid-cols-[minmax(0,2.3fr)_minmax(320px,1fr)] lg:gap-6">
          <!-- 左：本站 -->
          <div class="min-w-0">
            <div class="sh-head mb-2.5 flex items-center gap-1.5 text-[13px] font-semibold">
              <Icon name="grid" :size="14" class="text-brand" />本站<span class="font-mono text-mute">{{ left.length }}</span>
              <Icon v-if="site.refining" name="refresh" :size="13" class="ml-1 animate-spin text-brand" />
            </div>
            <p v-if="site.understanding" class="sh-und mb-3 flex items-start gap-1.5 rounded-[10px] px-3 py-2 text-[12.5px] leading-[19px]">
              <Icon name="sparkles" :size="13" class="mt-[3px] shrink-0 text-brand" /><span class="min-w-0"><b class="font-semibold text-brand">理解为：</b>{{ site.understanding }}</span>
            </p>
            <div v-if="leftLoading" class="grid gap-3 lg:grid-cols-3"><div v-for="n in 6" :key="n" class="skeleton-bar h-[96px] rounded-[10px] lg:h-[260px]" /></div>
            <div v-else-if="source === 'text' && site.state === 'error'" class="sh-empty">
              <span>{{ site.error }}</span><button class="btn-glass btn-sm mt-2" @click="retrySite"><Icon name="refresh" :size="14" />重试</button>
            </div>
            <div v-else-if="leftEmpty" class="sh-empty">本站暂无</div>
            <template v-else>
              <!-- 电脑：带封面图的卡片网格 -->
              <div class="hidden gap-3.5 lg:grid lg:grid-cols-3">
                <div
                  v-for="(x, k) in left"
                  :key="x.key"
                  class="sh-lcard relative min-w-0 rounded-lg"
                  :class="[enterOf[x.key]?.cls, compareOn && inCompare(leftEntry(x)) ? 'is-on' : '']"
                  :style="{ animationDelay: enterOf[x.key]?.delay }"
                  @click.capture="onLeftCard($event, x)"
                >
                  <span v-if="k === 0 && site.refined && x.reason" class="sh-best pointer-events-none absolute -top-2 left-3 z-20 rounded-full px-2 text-[11px] leading-5 font-semibold shadow-[0_6px_14px_-6px_rgb(30_86_214/0.8)]">最匹配</span>
                  <!-- 正在对比中：盖住卡片上的「对比」勾选，显示转圈 -->
                  <span v-if="compareOn && isComparing(leftEntry(x))" class="absolute top-2 right-2 z-20 inline-flex h-7 items-center gap-1 rounded-full bg-white/92 px-2.5 text-[12px] text-brand shadow-[0_4px_12px_-6px_rgb(11_47_122/0.6)]" :title="COMPARING_TIP">
                    <Icon name="refresh" :size="13" class="animate-spin" />对比中
                  </span>
                  <ItemCard v-if="x.item" :item="x.item" :index="0" class="h-full" />
                  <div v-else class="sh-card relative h-full rounded-[10px] p-3">
                    <CheckBox v-if="compareOn && !isComparing(leftEntry(x))" tone="compare" class="absolute top-2.5 right-2.5" :checked="inCompare(leftEntry(x))" @toggle="tapLeft(x)" />
                    <RouterLink :to="itemLink(x.id)" class="text-[14px] font-semibold underline decoration-ink/35 underline-offset-4 hover:text-brand">{{ x.name }}</RouterLink>
                    <p class="mt-1 mb-0 line-clamp-3 text-[12.5px] leading-[19px] text-ink-2">{{ x.summary || '暂无描述' }}</p>
                  </div>
                </div>
              </div>
              <!-- 手机 / 平板：与小程序一致的紧凑卡片 -->
              <div class="flex flex-col gap-2 lg:hidden">
                <div
                  v-for="(x, k) in left"
                  :key="x.key"
                  class="sh-card flex gap-2 rounded-[10px] p-2.5"
                  :class="[enterOf[x.key]?.cls, compareOn && inCompare(leftEntry(x)) ? 'is-on' : '']"
                  :style="{ animationDelay: enterOf[x.key]?.delay }"
                  @click="tapLeft(x)"
                >
                  <div v-if="compareOn" class="w-5 shrink-0 pt-0.5" @click.stop>
                    <button v-if="isComparing(leftEntry(x))" class="text-brand" :title="COMPARING_TIP" @click="toast(COMPARING_TIP, 'info', 2600)"><Icon name="refresh" :size="15" class="animate-spin" /></button>
                    <CheckBox v-else tone="compare" :checked="inCompare(leftEntry(x))" @toggle="tapLeft(x)" />
                  </div>
                  <div class="min-w-0 flex-1">
                    <div class="flex items-start gap-1">
                      <RouterLink :to="itemLink(x.id)" class="min-w-0 flex-1 text-[13.5px] leading-5 font-semibold break-all underline decoration-ink/35 underline-offset-4" @click.stop>{{ x.name }}</RouterLink>
                      <span v-if="k === 0 && site.refined && x.reason" class="sh-best shrink-0 rounded-full px-1.5 text-[10.5px] leading-[18px] font-semibold">最匹配</span>
                    </div>
                    <p class="mt-0.5 mb-0 line-clamp-3 text-[12px] leading-[18px] text-ink-2">{{ x.summary || '暂无描述' }}</p>
                    <p v-if="x.reason" class="sh-reason mt-1.5 mb-0 flex items-start gap-1 rounded-[7px] px-1.5 py-1 text-[11.5px] leading-[16px]">
                      <Icon name="sparkles" :size="11" class="mt-[2px] shrink-0" /><span class="line-clamp-2 min-w-0 flex-1">{{ x.reason }}</span>
                    </p>
                  </div>
                </div>
              </div>
            </template>
          </div>

          <!-- 右：GitHub（电脑上贴顶、独立滚动） -->
          <div class="min-w-0 lg:sticky lg:top-[72px] lg:flex lg:max-h-[calc(100vh-88px)] lg:flex-col">
            <div class="sh-head mb-2.5 flex items-center gap-1.5 text-[13px] font-semibold">
              <Icon name="github" :size="14" class="text-ink" />GitHub<span class="font-mono text-mute">{{ right.length }}</span>
            </div>
            <div class="min-h-0 lg:-mr-2 lg:overflow-y-auto lg:pr-2 lg:pb-2">
              <button v-if="source === 'text' && gh.state === 'guest'" class="sh-guest flex w-full cursor-pointer flex-col items-start rounded-[10px] p-3.5 text-left" @click="loginForGithub">
                <Icon name="github" :size="18" class="text-brand" />
                <b class="mt-1.5 text-[13.5px] font-semibold">登录后同时搜 GitHub</b>
              </button>
              <template v-else>
                <div v-if="source === 'text' && gh.state !== 'idle'" class="sh-flowbar mb-2.5 rounded-[12px] px-3 py-2.5">
                  <GhFlow :nodes="flow.nodes" :active="flow.active" :keywords="flow.keywords" :group="flow.group" :summary="flowSummary" :failed="ghErr && !isQuotaCode(ghErr.code) ? ghErr.msg : ''" />
                  <ErrorNote v-if="ghErr && isQuotaCode(ghErr.code)" class="mt-2.5" :message="ghErr.msg" :code="ghErr.code" @retry="retryGithub" />
                  <button v-else-if="ghErr" class="btn-primary btn-sm mt-2.5 w-full justify-center sm:w-auto" @click="retryGithub"><Icon name="refresh" :size="14" />重试</button>
                </div>
                <div v-if="ghLoading" class="flex flex-col gap-2"><div v-for="n in 3" :key="n" class="skeleton-bar h-[86px] rounded-[10px]" /></div>
                <div v-else-if="rightEmpty" class="sh-empty">
                  <span>{{ source === 'image' && shot.state === 'empty' ? '图片里没有识别到 Skill 或模型' : 'GitHub 上没有新的结果' }}</span>
                  <button v-if="source === 'image'" class="btn-glass btn-sm mt-2" @click="pickImage">重选图片</button>
                </div>
                <div v-else class="flex flex-col gap-2">
                  <div
                    v-for="x in right"
                    :key="x.key"
                    class="sh-card flex cursor-pointer gap-2 rounded-[10px] p-2.5 lg:gap-2.5 lg:p-3"
                    :class="[enterOf[x.key]?.cls, (compareOn ? inCompare(rightEntry(x)) : sel.has(x.key)) ? 'is-on' : '']"
                    :style="{ animationDelay: enterOf[x.key]?.delay }"
                    @click="tapRight(x)"
                  >
                    <div class="w-5 shrink-0 pt-0.5" @click.stop>
                      <button v-if="compareOn && isComparing(rightEntry(x))" class="text-brand" :title="COMPARING_TIP" @click="toast(COMPARING_TIP, 'info', 2600)"><Icon name="refresh" :size="15" class="animate-spin" /></button>
                      <CheckBox v-else-if="compareOn" tone="compare" :checked="inCompare(rightEntry(x))" @toggle="tapRight(x)" />
                      <button v-else-if="x.state === 'importing'" class="text-brand" :title="JOINING_TIP" @click="toast(JOINING_TIP, 'info', 2600)"><Icon name="refresh" :size="15" class="animate-spin" /></button>
                      <CheckBox v-else :checked="sel.has(x.key)" @toggle="tapRight(x)" />
                    </div>
                    <div class="min-w-0 flex-1">
                      <div class="flex items-start gap-1.5">
                        <span class="min-w-0 flex-1 text-[13.5px] leading-5 font-semibold break-all lg:text-[14px]">{{ x.name }}</span>
                        <span v-if="x.state === 'importing'" class="shrink-0 text-[11px] leading-5 text-brand">加入中…</span>
                        <a :href="`https://github.com/${x.full_name}`" target="_blank" rel="noopener" class="hidden h-5 w-5 shrink-0 place-items-center rounded text-mute hover:text-brand lg:grid" title="在 GitHub 上打开" @click.stop><Icon name="external-link" :size="13" /></a>
                      </div>
                      <Transition name="sh-zh" mode="out-in">
                        <p :key="x.zh ? 'zh' : 'en'" class="mt-0.5 mb-0 line-clamp-3 text-[12px] leading-[18px] text-ink-2 lg:text-[12.5px] lg:leading-[19px]">{{ x.zh || x.summary || x.full_name }}</p>
                      </Transition>
                      <p class="mt-1 mb-0 hidden items-center gap-2 font-mono text-[11px] text-mute lg:flex">
                        <span class="min-w-0 truncate">{{ x.full_name }}</span>
                        <span v-if="x.stars != null" class="ml-auto shrink-0">★ {{ formatStars(x.stars) }}</span>
                      </p>
                    </div>
                  </div>
                </div>
              </template>
            </div>
          </div>
        </div>
      </div>
    </div>

    <JoinBar :show="active && homeOn && phase === 'results' && !compareOn && picked.length > 0" :count="picked.length" :note="importingN ? `另有 ${importingN} 个加入中` : ''" :posting="joining" @join="doJoin" />
  </section>
</template>

<style scoped>
.sh-idle { min-height: calc(100svh - 56px - 64px); }
.sh-box { border-color: var(--color-line); box-shadow: 0 18px 44px -28px rgb(11 47 122 / 0.55); transition: border-color 0.25s, box-shadow 0.25s; }
.sh-box.is-focus { border-color: rgb(30 86 214 / 0.55); box-shadow: 0 0 0 4px rgb(30 86 214 / 0.1), 0 18px 44px -28px rgb(11 47 122 / 0.55); }
.sh-box.is-drag { border-style: dashed; border-color: var(--color-brand); background: var(--color-brand-soft); }
.sh-panel { box-shadow: 0 22px 48px -20px rgb(11 47 122 / 0.5); }
.sh-row { animation: shrow 0.35s var(--ease-out-expo) backwards; animation-delay: var(--d, 0ms); }
.sh-card { border: 1px solid var(--color-line); background: #fff; transition: border-color 0.25s, box-shadow 0.25s, transform 0.25s; }
.sh-card:hover { border-color: rgb(30 86 214 / 0.35); box-shadow: 0 10px 24px -18px rgb(11 47 122 / 0.6); }
.sh-lcard.is-on { box-shadow: 0 0 0 2px rgb(30 86 214 / 0.55); }
.sh-card.is-on { border-color: rgb(30 86 214 / 0.5); box-shadow: 0 0 0 2px rgb(30 86 214 / 0.12); }
.sh-in { animation: shin 0.45s var(--ease-out-expo) backwards; }
.sh-fly { animation: shfly 0.55s var(--ease-out-expo) backwards; }
.sh-und { background: rgb(30 86 214 / 0.06); color: var(--color-ink-2); }
.sh-reason { background: rgb(30 86 214 / 0.06); color: var(--color-brand); }
.sh-best { background: linear-gradient(135deg, #2f6bf0, #1e56d6); color: #fff; }
.sh-flowbar { background: rgb(255 255 255 / 0.8); box-shadow: inset 0 0 0 1px var(--color-line); }
.sh-guest { border: 1px dashed rgb(30 86 214 / 0.35); background: rgb(30 86 214 / 0.04); }
.sh-empty { display: flex; flex-direction: column; align-items: center; padding: 28px 8px; text-align: center; font-size: 13px; color: var(--color-mute); }
.sh-hit { cursor: pointer; }
.sh-float { animation: shfloat var(--dur, 5s) ease-in-out infinite; }
.sh-spin { animation: shspin 28s linear infinite; }
.sh-bob { animation: shbob 4.8s ease-in-out infinite; }
.sh-breath { animation: shbreath 6s ease-in-out infinite; }
.sh-twinkle { animation: shtwinkle 3.2s ease-in-out infinite; animation-delay: var(--d, 0s); }
.pk-spin { animation: pkspin 0.8s cubic-bezier(0.3, 1.4, 0.5, 1); }
.pk-flip { animation: pkflip 0.8s cubic-bezier(0.3, 1.3, 0.5, 1); }
.pk-wobble { animation: pkwobble 0.75s ease-in-out; }
.pk-pop { animation: pkpop 0.8s cubic-bezier(0.3, 1.5, 0.5, 1); }
.pk-late { animation-delay: 0.08s; }
.pk-hop { animation: pkhop 0.7s cubic-bezier(0.3, 1.5, 0.5, 1); }
.pk-burst { animation: pkburst 0.7s ease-out; }
.sh-title-leave-active { transition: opacity 0.25s, transform 0.25s; }
.sh-title-leave-to { opacity: 0; transform: translateY(-8px); }
.sh-zh-enter-active { transition: opacity 0.5s ease-out; }
.sh-zh-enter-from { opacity: 0; }
@keyframes shrow { from { opacity: 0; transform: translateY(-4px); } }
@keyframes shin { from { opacity: 0; transform: translateY(10px); } }
@keyframes shfly { from { opacity: 0; transform: translateX(60px); } }
@keyframes shbob { 50% { transform: translateY(-4px); } }
@keyframes shbreath { 50% { opacity: 0.7; transform: scale(1.04); } }
@keyframes shtwinkle { 0%, 100% { opacity: 0.25; transform: scale(0.7); } 50% { opacity: 1; transform: scale(1.1); } }
@keyframes shfloat { 50% { transform: translateY(var(--amp, -6px)); } }
@keyframes shspin { to { transform: rotate(360deg); } }
@keyframes pkspin { to { transform: rotate(360deg); } }
@keyframes pkflip { 0% { transform: rotate(0); } 60% { transform: rotate(380deg) scale(1.08); } 100% { transform: rotate(360deg); } }
@keyframes pkwobble { 0%, 100% { transform: rotate(0); } 20% { transform: rotate(-7deg) scale(1.04); } 45% { transform: rotate(6deg); } 70% { transform: rotate(-3deg); } }
@keyframes pkpop { 0%, 100% { transform: translateY(0); } 40% { transform: translateY(-26px) rotate(-6deg); } 70% { transform: translateY(4px); } }
@keyframes pkhop { 0%, 100% { transform: translateY(0) rotate(0); } 35% { transform: translateY(-16px) rotate(-8deg); } 65% { transform: translateY(2px) rotate(4deg); } }
@keyframes pkburst { 0% { transform: scale(1) rotate(0); } 40% { transform: scale(1.5) rotate(25deg); opacity: 1; } 100% { transform: scale(1) rotate(0); } }
@media (prefers-reduced-motion: reduce) {
  .sh-float, .sh-spin, .sh-bob, .sh-breath, .sh-twinkle, .sh-in, .sh-fly, .sh-row { animation: none; }
}
</style>
