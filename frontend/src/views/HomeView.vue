<script setup>
import { track } from '../composables/analytics'
import { computed, nextTick, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch, watchEffect } from 'vue'
import { ghView } from '../composables/ghView'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'
import { api, formatStars, isCancelled } from '../api'
import { toast } from '../composables/toast'
import { useCountUp } from '../composables/countUp'
import { groupStyle, kindStyle } from '../categoryStyle'
import Icon from '../components/Icon.vue'
import ItemCard from '../components/ItemCard.vue'
import GithubPanel from '../components/GithubPanel.vue'
import CompareModeToggle from '../components/CompareModeToggle.vue'
import AiTag from '../components/AiTag.vue'
import Seg from '../components/Seg.vue'
import { favState } from '../composables/favorites'
import { maybeShowTour, openTour } from '../composables/onboarding'
import { bannerDismissed, dismissBanner, homeConfig, loadHomeConfig } from '../composables/homeConfig'
import { rememberSearch } from '../composables/searchHistory'
import { isSubscribed, loadSubs, noteState, toggleSub } from '../composables/notifications'
import SearchAssist from '../components/SearchAssist.vue'
import { authState, initAuth, isAdminUser, requireLogin } from '../composables/auth'
import { meta as metaStore, loadMeta as fetchMeta } from '../composables/meta'
import { goCollect, homeSignal } from '../composables/collect'
import { reduceMotion } from '../composables/motion'

const route = useRoute()
const router = useRouter()

const tree = ref([])
const items = ref([])
const total = ref(0)
const page = ref(1)
const loading = ref(true)
const firstLoad = ref(true)
const listVersion = ref(0)
const error = ref('')
const keyword = ref(route.query.q || '')
const meta = ref(null)

// 筛选条件以 URL 为准，打开 / 关闭详情抽屉时保留。默认排序「今日」：当天星标涨得多的在前，其余每天换个顺序
const filters = computed(() => ({
  q: route.query.q || '',
  category: route.query.category || '',
  source: route.query.source || '',
  kind: route.query.kind || '',
  sort: route.query.sort || 'today',
}))
watch(() => route.query.exact, () => (filters.value.q ? semanticSearch() : null))
const kinds = computed(() => metaStore.data?.kinds || [])

const activeGroup = computed(() => {
  const code = filters.value.category
  if (!code) return null
  return tree.value.find((g) => g.code === code || g.children.some((c) => c.code === code)) || null
})

const totalCount = computed(() => tree.value.reduce((s, g) => s + g.item_count, 0))
const allCount = computed(() => meta.value?.published_total ?? totalCount.value)
const leafCount = computed(() => tree.value.reduce((s, g) => s + g.children.length, 0))

const SOURCES = [['', '全部'], ['auto', '系统采集'], ['manual', '手动上传']]
// v3.3 登录后多一个「为你推荐」（按收藏和浏览过的分类推同类）
const SORTS = computed(() => [...(authState.user ? [['foryou', '为你推荐', 'sparkles']] : []), ['today', '今日'], ['stars', '按星标'], ['collected', '最新收录']])
const kindOptions = computed(() => [['', '全部类型'], ...kinds.value.map((k) => [k.key, k.name, kindStyle(k.key).icon])])
const title = computed(() => {
  const g = activeGroup.value
  if (!g) return '全部条目'
  const leaf = g.children.find((c) => c.code === filters.value.category)
  return leaf ? leaf.name : g.name
})

// ---- 搜索范围：站内（默认，不用登录）/ GitHub（外站，需要登录，回车才搜）----
const scope = computed(() => (route.query.scope === 'github' ? 'github' : 'site'))
// v3.3.33 GitHub 面板第一次切过去才创建，之后切到站内或别的页面只隐藏不销毁（与小程序一致）：
// 正在检索 / AI 分析的过程、结果和勾选都保留；首页本身也被 KeepAlive 缓存（App.vue）
const ghMounted = ref(scope.value === 'github')
watch(scope, (v) => v === 'github' && (ghMounted.value = true))
const active = ref(true) // 首页是否在前台（被缓存到后台时为 false）
watchEffect(() => (ghView.shown = active.value && scope.value === 'github'))
// 详情抽屉只在首页自己的地址下渲染（缓存在后台时不跟着别的页面的地址渲染一份）
const ownRoute = computed(() => route.matched[0]?.path === '/')
const scopeModel = computed({ get: () => scope.value, set: (v) => setScope(v) })
const github = ref(null)
const input = ref(null)
const fileInput = ref(null)
const shell = ref(null)

async function setScope(v) {
  if (v === scope.value) return
  if (v === 'github' && !authState.user && !(await requireLogin('在 GitHub 上找、收录项目需要先登录'))) return
  // v3.3.26 切换时保留输入框里的文字（与小程序一致）：切回站内直接按这段文字搜索，切到 GitHub 留着等回车
  await setQuery({ scope: v === 'github' ? 'github' : '', q: v === 'site' ? keyword.value.trim() : '' })
  restartTyping()
  // v3.3.34 触屏设备切换范围后不自动聚焦（一聚焦就弹键盘，挡住页面，三端统一）；有鼠标的电脑上仍然聚焦方便直接输入。
  // 底栏「+」里的「本站搜索 / 收录」是用户主动要输入的入口，照旧聚焦（homeSignal.focus）
  if (matchMedia('(hover: hover) and (pointer: fine)').matches) nextTick(() => input.value?.focus())
}

function searchGithub(text) {
  if (text) keyword.value = text
  const q = keyword.value.trim()
  if (!q) return
  track('search', { q: q.slice(0, 100), scope: 'github' })
  github.value?.run(q)
}

function onSubmit() {
  assistOpen.value = false
  if (scope.value === 'github') searchGithub()
  else {
    searchSite()
    rememberSearch(keyword.value)
    input.value?.blur()
  }
}

// ---- v3.3 搜索增强：下拉里的最近搜索 / 大家在搜 / 联想 ----
const assistOpen = ref(false)
const shellWrap = ref(null)
function pickSuggestion(q) {
  keyword.value = q
  clearTimeout(timer)
  setQuery(searchPatch(q))
  rememberSearch(q)
  assistOpen.value = false
  input.value?.blur()
}
function openSuggestion(id) {
  rememberSearch(keyword.value)
  assistOpen.value = false
  input.value?.blur()
  router.push({ path: `/items/${id}`, query: route.query })
}
function onDocDown(e) {
  if (assistOpen.value && shellWrap.value && !shellWrap.value.contains(e.target)) assistOpen.value = false
}
// 停下来 1.5 秒的搜索词记进本机历史（边输边搜的半截词不记）
let historyTimer
watch(() => filters.value.q, (q) => {
  clearTimeout(historyTimer)
  if (q) historyTimer = setTimeout(() => rememberSearch(q), 1500)
})
// GitHub 标签下是多行输入：回车搜索，Shift + 回车换行。
// v3.3.10 站内搜索也改成自动长高的输入框：文字超过一行就换到第二行显示（回车直接搜索，不换行）
function onEnter(e) {
  if (e.isComposing) return
  if (scope.value !== 'github') {
    e.preventDefault()
    onSubmit()
    return
  }
  if (e.shiftKey) return
  e.preventDefault()
  searchGithub()
}
// v3.3.32 站内和 GitHub 都最多显示两行（三端统一）：框高封顶两行，第三行起在框内滚动，
// 始终滚到最后一行（第一行被顶上去，正在输入的那行露出来）；放大镜、相机、清空按钮一律上下居中
const LINE = 24
function autosize() {
  const el = input.value
  if (!el || el.tagName !== 'TEXTAREA') return
  const cs = getComputedStyle(el)
  const max = parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom) + LINE * 2
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, max)}px`
  if (el.scrollHeight > max) el.scrollTop = el.scrollHeight
}
// v3.3.31 一键清空（三端统一）：有文字时在文字后面出现小叉；点一下清空、高度回到一行、光标留在输入框里接着输入。
// 站内搜索会回到全部条目（沿用「清空即重置」），并重新打开联想下拉
function clearKeyword() {
  keyword.value = ''
  nextTick(() => {
    autosize()
    input.value?.focus()
    if (scope.value === 'site') assistOpen.value = true
  })
}
watch([keyword, scope], () => nextTick(autosize))
// v3.3.28 输入框变窄 / 变宽时也重算高度：比如点搜索后按钮变成更宽的「处理中」，文字被挤成两行，
// 原来高度不跟着变，第二行被裁掉。至少要把第二行（直到最后一个字）显示出来。
let inputRo
watch(input, (el) => {
  inputRo?.disconnect()
  if (!el || typeof ResizeObserver === 'undefined') return
  let w = el.clientWidth
  inputRo = new ResizeObserver(() => {
    if (el.clientWidth !== w) {
      w = el.clientWidth
      autosize()
    }
  })
  inputRo.observe(el)
})
onBeforeUnmount(() => inputRo?.disconnect())

// ---- 图片 / 文本文件：相机按钮、拖到搜索框上、Ctrl V 粘贴 → 截图识别 / 逐个识别 ----
const dragging = ref(false)
async function takeFile(file) {
  if (!file) return
  if (scope.value !== 'github') {
    if (!authState.user && !(await requireLogin('截图识别需要先登录'))) return
    keyword.value = ''
    if (!ghMounted.value) github.value = null // v3.3.26 面板还没创建过：等新面板挂好再交图片；已存在（隐藏中）就直接交给它
    await router.replace({ path: '/', query: { ...route.query, scope: 'github', q: undefined } })
  }
  // 等 GitHub 结果区挂载好（切标签有过渡）再交给它识别
  for (let i = 0; i < 60 && !github.value; i++) await new Promise((r) => setTimeout(r, 50))
  github.value?.addFile(file)
  shell.value?.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'start' })
}
function onPickFile(e) {
  takeFile(e.target.files?.[0])
  e.target.value = ''
}
function onDrop(e) {
  dragging.value = false
  takeFile(e.dataTransfer.files?.[0])
}
function onPaste(e) {
  const f = [...(e.clipboardData?.files || [])].find((x) => x.type.startsWith('image/'))
  if (f && !route.params.id) {
    e.preventDefault()
    takeFile(f)
  }
}
// v3.1 相机按钮：未登录先弹登录框（原来直接打开选文件框，选完才提示登录，看起来像没反应）；
// 登录后切到 GitHub 标签。浏览器只允许在点击当下打开选文件框，所以登录完成后请用户再点一次
async function pickFile() {
  if (authState.user) {
    fileInput.value?.click()
    return
  }
  if (!(await requireLogin('截图识别需要先登录'))) return
  keyword.value = ''
  await router.replace({ path: '/', query: { ...route.query, scope: 'github', q: undefined } })
  toast('已登录，点相机选择截图', 'success')
}
watch(() => homeSignal.focus, () => nextTick(() => input.value?.focus()))
watch(() => homeSignal.pickFile, () => nextTick(pickFile))

// ---- 打字机占位：站内轮播搜索示例，GitHub 轮播四种用法 ----
const TIPS = {
  site: ['PPT 自动生成', '截图转文字', '中文语音识别模型', '代码评审 Skill', 'MCP 浏览器自动化'],
  github: ['说说想要的功能，例如：会议纪要整理', '贴 GitHub 仓库地址，直接收录', '贴文章链接或一段长文，逐个识别', '粘贴截图，识别里面的项目'],
}
const placeholder = ref('')
let typer
let tipI = 0
let charI = 0
let deleting = false
function typeTick() {
  const pre = scope.value === 'site' ? '搜索本站：' : ''
  if (document.activeElement === input.value || keyword.value) {
    typer = setTimeout(typeTick, 600)
    return
  }
  // v3.3.71 后台配置了搜索框提示词时，站内搜索轮播用后台的
  const list = scope.value === 'site' && homeConfig.searchPlaceholders.length ? homeConfig.searchPlaceholders : TIPS[scope.value]
  const full = pre + list[tipI % list.length]
  charI += deleting ? -1 : 1
  placeholder.value = full.slice(0, Math.max(pre.length, charI)) + (charI < full.length && !deleting ? '▍' : '')
  let wait = deleting ? 30 : 90
  if (!deleting && charI >= full.length) {
    deleting = true
    wait = 1800
  } else if (deleting && charI <= pre.length) {
    deleting = false
    tipI++
    wait = 300
  }
  typer = setTimeout(typeTick, wait)
}
function restartTyping() {
  clearTimeout(typer)
  tipI = 0
  charI = 0
  deleting = false
  if (reduceMotion) placeholder.value = scope.value === 'site' ? '搜索本站：名称、功能描述、仓库' : '说说想要的功能，或贴仓库地址、文章链接、截图'
  else typeTick()
}

// Ctrl / ⌘ + K 聚焦搜索框
const kbdPress = ref(false)
const flash = ref(false)
function onKey(e) {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault()
    input.value?.focus()
    kbdPress.value = true
    setTimeout(() => (kbdPress.value = false), 180)
    flash.value = false
    requestAnimationFrame(() => (flash.value = true))
  }
}

// 页头网格：鼠标所在处的格子亮起来
const hero = ref(null)
function onHeroMove(e) {
  const r = hero.value.getBoundingClientRect()
  hero.value.style.setProperty('--hx', `${e.clientX - r.left}px`)
  hero.value.style.setProperty('--hy', `${e.clientY - r.top}px`)
}

// ---- 手机：主搜索框滑出屏幕后，顶部出现紧凑搜索条；往下滑收起、往上滑出现 ----
const mini = ref(false)
const headerH = ref(56)
let lastY = 0
function onScroll() {
  const y = window.scrollY
  const below = shell.value ? shell.value.getBoundingClientRect().bottom < headerH.value : false
  if (!below || innerWidth >= 640) mini.value = false
  else if (y < lastY - 4) mini.value = true
  else if (y > lastY + 4) mini.value = false
  lastY = y
}
const activeFilters = computed(() => ['category', 'source', 'kind'].filter((k) => filters.value[k]).length + (filters.value.sort !== 'today' ? 1 : 0))
function toFilters() {
  mini.value = false
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

// 退出登录时回到站内搜索
watch(() => authState.user, (u) => !u && authState.ready && scope.value === 'github' && setQuery({ scope: '' }))

// v3.3.7 从铃铛面板「去订阅」过来（?sub=1）：「订阅上新」按钮闪几下，告诉用户在哪里点
const subFlash = ref(false)
watch(
  () => route.query.sub,
  (v) => {
    if (!v) return
    subFlash.value = true
    setTimeout(() => (subFlash.value = false), 2600)
    setQuery({ sub: '' })
    nextTick(() => document.querySelector('.sub-btn')?.scrollIntoView({ block: 'center', behavior: 'smooth' }))
  },
  { immediate: true },
)

function setQuery(patch) {
  const q = { ...route.query, ...patch }
  for (const k of Object.keys(q)) if (!q[k] || (k === 'sort' && q[k] === 'today')) delete q[k]
  return router.replace({ path: '/', query: q })
}

// ---- 语义搜索：输入时先即时显示名称匹配，停顿后切到语义结果（可切回「仅名称匹配」）----
const sem = ref(null)
const semLoading = ref(false)
const aiRefining = ref(false)
const exactOnly = computed(() => route.query.exact === '1')
let semSeq = 0

async function semanticSearch() {
  const q = filters.value.q
  sem.value = null
  if (q) track('search', { q: q.slice(0, 100), exact: !!exactOnly.value })
  if (!q || exactOnly.value) return
  const seq = ++semSeq
  semLoading.value = true
  aiRefining.value = false
  const p = new URLSearchParams({ q, kind: filters.value.kind, category: filters.value.category })
  try {
    const r = await api(`/api/search?${p}`)
    if (seq !== semSeq) return
    if (r.mode === 'semantic') sem.value = r
  } catch {
    // 语义搜索失败时保留名称匹配结果
  } finally {
    if (seq === semSeq) semLoading.value = false
  }
  if (seq !== semSeq || !sem.value?.ai_pending) return
  aiRefining.value = true
  try {
    p.set('stage', 'ai')
    const r = await api(`/api/search?${p}`)
    if (seq === semSeq && r.mode === 'semantic') sem.value = r
  } catch {
    // AI 精排失败时保留向量结果
  } finally {
    if (seq === semSeq) aiRefining.value = false
  }
}

const shown = computed(() => (sem.value ? sem.value.items : items.value))
const shownTotal = computed(() => (sem.value ? sem.value.items.length : total.value))

async function load(reset = true) {
  if (reset) page.value = 1
  loading.value = true
  error.value = ''
  try {
    const params = new URLSearchParams({ ...filters.value, page: page.value, size: 24 })
    const data = await api(`/api/items?${params}`)
    if (reset) {
      items.value = data.items
      listVersion.value++
    } else {
      items.value = [...items.value, ...data.items]
    }
    total.value = data.total
    if (reset) semanticSearch()
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
    firstLoad.value = false
  }
}

function more() {
  page.value++
  load(false)
}
// v3.3.30 翻页：只有宽屏（三栏，榜单在右侧栏、列表下面没有别的内容）滚到「加载更多」时自动加载；
// 手机和平板列表下面还有榜单等内容，不自动加载，点「加载更多」才翻页（与小程序一致）
const moreEl = ref(null)
let moreIo
watch(moreEl, (el) => {
  moreIo?.disconnect()
  if (!el || typeof IntersectionObserver === 'undefined') return
  moreIo = new IntersectionObserver(([e]) => {
    if (e.isIntersecting && matchMedia('(min-width: 1024px)').matches && !loading.value && items.value.length < total.value) more()
  }, { rootMargin: '0px 0px 240px 0px' })
  moreIo.observe(el)
})
onBeforeUnmount(() => moreIo?.disconnect())

async function loadMeta() {
  const d = await fetchMeta(true)
  if (d) {
    meta.value = d
    favState.count = d.favorites
  }
}

async function translateAll() {
  try {
    const r = await api('/api/items/reextract-pending', { method: 'POST', admin: true })
    toast(`已开始处理 ${r.queued} 个条目，稍后刷新查看`, 'success', 3500)
    meta.value.untranslated = 0
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  }
}

function pickCategory(code) {
  setQuery({ category: code })
}
function pickFromBars(code) {
  pickCategory(code)
  document.querySelector('.home-main')?.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'start' })
}

// ---- 右栏：今日 / 本周增速、分类分布、最新收录 ----
const period = ref('daily')
const movers = ref({ daily: null, weekly: null })
const fresh = ref([])
async function loadMovers(p) {
  if (movers.value[p]) return
  try {
    const r = await api(`/api/rankings?period=${p}`)
    const seen = new Set()
    movers.value[p] = r.boards
      .flatMap((b) => b.entries)
      .sort((a, b) => b.stars_delta - a.stars_delta)
      .filter((e) => {
        const k = e.item.repo_full_name || e.item.id
        return !seen.has(k) && seen.add(k)
      })
      .slice(0, 6)
  } catch {
    movers.value[p] = []
  }
}
watch(period, loadMovers)
const moverList = computed(() => movers.value[period.value] || [])
const maxDelta = computed(() => moverList.value[0]?.stars_delta || 1)
const rankIn = ref(false)
watch(moverList, () => {
  rankIn.value = false
  requestAnimationFrame(() => requestAnimationFrame(() => (rankIn.value = true)))
})
const maxGroup = computed(() => Math.max(1, ...tree.value.map((g) => g.item_count)))

async function loadFresh() {
  try {
    fresh.value = (await api('/api/items?sort=collected&size=6')).items
  } catch {}
}
const hm = (iso) => {
  const d = new Date(iso)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

// 只等后台的「已发布总数」到了再数到位；先用分类合计再换数会出现 513→514 这种跳动
const statItems = useCountUp(computed(() => meta.value?.published_total ?? 0))
const statCats = useCountUp(leafCount)
const statToday = useCountUp(computed(() => meta.value?.today_new ?? 0))
// v3.2.1：第四个指标由「最高日增」改为「今日下架」
const statOff = useCountUp(computed(() => meta.value?.today_offline ?? 0))

// ---- 左栏 / 手机分类条：选中底块滑动 ----
const sideNav = ref(null)
const sideThumb = ref({ opacity: 0 })
const chips = ref(null)
const chipThumb = ref({ opacity: 0 })
function measureNav() {
  const s = sideNav.value?.querySelector('[aria-current="true"]')
  sideThumb.value = s ? { transform: `translateY(${s.offsetTop}px)`, height: `${s.offsetHeight}px`, opacity: 1 } : { opacity: 0 }
  const c = chips.value?.querySelector('[aria-pressed="true"]')
  chipThumb.value = c ? { transform: `translateX(${c.offsetLeft}px)`, width: `${c.offsetWidth}px`, opacity: 1 } : { opacity: 0 }
  if (c && chips.value) chips.value.scrollTo({ left: c.offsetLeft - chips.value.clientWidth / 2 + c.offsetWidth / 2, behavior: reduceMotion ? 'auto' : 'smooth' })
}
watch([() => filters.value.category, tree, scope], () => nextTick(measureNav))

let timer
watch(keyword, (v) => {
  clearTimeout(timer)
  // v3.3.27 站内搜索也不再边输入边搜（会打断打字和语音输入，三端统一）：按回车 / 点「搜索」/ 点联想词才搜；
  // 只有把输入框清空时立刻回到全部条目
  // v3.3.28 站内不换行：粘贴进来的多行合成一行（回车直接搜索）
  if (scope.value === 'site' && v.includes('\n')) {
    keyword.value = v.replace(/\s*\n+\s*/g, ' ')
    return
  }
  if (scope.value === 'site' && !v.trim() && filters.value.q) setQuery({ q: '' })
})
function searchSite() {
  clearTimeout(timer)
  const q = keyword.value.trim()
  if (q !== filters.value.q) setQuery(searchPatch(q))
}
// v3.3.16 搜索词从空变成非空（一次新搜索）时，分类回到「全部」，免得残留的分类筛选把结果筛成 0 条；
// 已经在搜、只是改词时不动分类（在结果里点分类继续筛，照旧）。与小程序一致。
function searchPatch(q) {
  return q && !filters.value.q && filters.value.category ? { q, category: '' } : { q }
}
// 只在列表和抽屉路由上响应筛选变化（离开页面时 query 清空不应触发加载）
watch(filters, () => (route.path === '/' || /^\/items\/\d+$/.test(route.path)) && load(), { deep: true })
watch(() => authState.version, () => load())

// v3.3.33 首页被缓存后：到别的页面时停掉全局监听（否则在口袋页粘贴图片也会被首页拿去识别），回来再挂上
function listen(on) {
  const f = on ? addEventListener : removeEventListener
  f('scroll', onScroll, { passive: true })
  f('keydown', onKey)
  f('paste', onPaste)
  f('pointerdown', onDocDown)
  f('resize', measureNav)
}
let firstActivate = true
onActivated(() => {
  active.value = true
  if (firstActivate) return (firstActivate = false) // 首次挂载由 onMounted 处理
  listen(true)
  restartTyping()
  nextTick(measureNav)
})
onDeactivated(() => {
  active.value = false
  listen(false)
  clearTimeout(typer)
  assistOpen.value = false
})
onMounted(async () => {
  headerH.value = document.querySelector('header')?.offsetHeight || 56
  addEventListener('scroll', onScroll, { passive: true })
  addEventListener('keydown', onKey)
  addEventListener('paste', onPaste)
  addEventListener('pointerdown', onDocDown)
  maybeShowTour()
  loadHomeConfig()
  if (authState.user && !noteState.subs) loadSubs()
  addEventListener('resize', measureNav)
  restartTyping()
  if (route.query.denied) {
    toast('这个页面只有管理员可以访问', 'error')
    setQuery({ denied: '' })
  }
  if (scope.value === 'github') {
    await initAuth()
    if (!authState.user && !(await requireLogin('在 GitHub 上找、收录项目需要先登录'))) setQuery({ scope: '' })
    else if (route.query.shot) {
      setQuery({ shot: '' })
      nextTick(() => fileInput.value?.click())
    }
  }
  load()
  loadMeta()
  loadMovers('daily')
  loadFresh()
  try {
    tree.value = await api('/api/categories')
  } catch {}
  document.fonts?.ready.then(measureNav)
})
onBeforeUnmount(() => {
  clearTimeout(typer)
  removeEventListener('scroll', onScroll)
  removeEventListener('keydown', onKey)
  removeEventListener('paste', onPaste)
  removeEventListener('pointerdown', onDocDown)
  removeEventListener('resize', measureNav)
})
</script>

<template>
  <div>
    <!-- v3.3.71 首页公告横幅（后台「运营工具」配置；关掉后同一条不再出现） -->
    <div
      v-if="homeConfig.banner && !bannerDismissed(homeConfig.banner.id)"
      class="relative z-30 border-b px-4 py-2 text-[13px] md:px-6"
      :class="homeConfig.banner.level === 'warn' ? 'border-warn/30 bg-warn-soft text-warn' : homeConfig.banner.level === 'success' ? 'border-ok/30 bg-ok-soft text-ok' : 'border-brand/20 bg-brand-soft text-brand'"
      role="status"
    >
      <div class="mx-auto flex max-w-[1440px] items-center gap-2">
        <Icon name="bell" :size="15" class="shrink-0" />
        <RouterLink v-if="homeConfig.banner.link" :to="homeConfig.banner.link" class="min-w-0 flex-1 truncate font-medium hover:underline">{{ homeConfig.banner.text }}</RouterLink>
        <span v-else class="min-w-0 flex-1 truncate font-medium">{{ homeConfig.banner.text }}</span>
        <button class="grid h-7 w-7 shrink-0 place-items-center rounded-md hover:bg-white/60" aria-label="关闭横幅" @click="dismissBanner(homeConfig.banner.id)"><Icon name="x" :size="14" /></button>
      </div>
    </div>
    <!-- 紧凑页头：标题 + 指标 + 搜索 -->
    <section ref="hero" class="hero relative z-20 border-b border-line bg-linear-180 from-white to-bg" @pointermove="onHeroMove">
      <!-- v3.3：装饰层单独裁切；页头本身不裁，搜索下拉才能伸出页头 -->
      <div class="pointer-events-none absolute inset-0 overflow-hidden">
      <div class="hero-grid" />
      <div class="hero-grid-hot" />
      <span class="hero-glow -top-[220px] -right-[120px] h-[420px] w-[420px] bg-[rgb(90_162_255/0.32)]" />
      <span class="hero-glow -top-10 -left-40 h-[300px] w-[300px] bg-[rgb(30_86_214/0.14)] [animation-delay:-8s] [animation-duration:26s]" />
      </div>
      <div class="relative mx-auto max-w-[1440px] px-4 pt-5 pb-[18px] md:px-6 md:pt-[26px] md:pb-[22px]">
        <div class="flex flex-wrap items-end gap-x-8 gap-y-4">
          <div class="min-w-0 flex-[1_1_420px]">
            <h1 v-reveal="0" class="m-0 text-2xl leading-8 font-semibold tracking-[-0.025em] md:text-[32px] md:leading-10">
              一起探索 <em class="text-gradient not-italic">开源世界</em>
            </h1>
            <!-- v3.3 一句话说明三个核心能力；点「怎么用」重新打开新手引导 -->
            <p v-reveal="1" class="mt-1.5 mb-0 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-[13px] leading-5 text-ink-2 md:text-[14px]">
              <span>GitHub 的中文中转站</span><i class="h-1 w-1 rounded-full bg-mute/60" /><span>你的技能口袋</span><i class="h-1 w-1 rounded-full bg-mute/60" /><span>AI 帮你对比选型</span>
              <button class="ml-1 inline-flex cursor-pointer items-center gap-0.5 text-brand hover:underline" @click="openTour"><Icon name="sparkles" :size="13" />怎么用</button>
            </p>
          </div>
          <div v-reveal="1" class="grid flex-[1_1_100%] grid-cols-4 overflow-hidden rounded-lg max-sm:hidden border border-line bg-white/85 min-[1100px]:flex-none min-[1100px]:grid-cols-[repeat(4,118px)]">
            <div
              v-for="(s, i) in [[statItems, '收录条目'], [statCats, '细分类别'], [statToday, '今日新增', true], [statOff, '今日下架']]"
              :key="s[1]"
              class="stat relative border-r border-line-2 px-2.5 py-2 transition-colors duration-300 last:border-r-0 hover:bg-brand-soft md:px-3.5 md:py-2.5"
            >
              <span class="cap block text-[10px] tracking-[0.06em] whitespace-nowrap">{{ s[1] }}</span>
              <b class="block font-mono text-lg leading-6 font-medium tracking-[-0.02em] whitespace-nowrap tabular-nums md:text-xl md:leading-7" :class="{ 'text-brand': s[2] }">{{ s[3] || '' }}{{ s[0].toLocaleString('en-US') }}</b>
            </div>
          </div>
        </div>

        <!-- v3.3.10 手机：搜索范围放在搜索框上方，输入框留出整行宽度（PC 仍在框内） -->
        <div v-reveal="2" class="mt-3.5 flex items-center sm:hidden">
          <Seg v-model="scopeModel" variant="line" label="搜索范围" :options="[['site', '站内', 'grid'], ['github', 'GitHub', 'github']]">
            <template #extra="{ option }"><Icon v-if="option[0] === 'github' && !authState.user" name="lock" :size="11" class="text-mute" /></template>
          </Seg>
        </div>
        <div ref="shellWrap" class="relative" @keydown.esc="assistOpen = false">
        <form
          ref="shell"
          v-reveal="2"
          class="search-shell mt-2 flex min-h-[50px] items-center gap-2 rounded-[10px] px-[5px] py-[5px] max-sm:pl-3 sm:mt-3.5"
          :class="{ flash, dragging }"
          role="search"
          @submit.prevent="onSubmit"
          @dragover.prevent="dragging = true"
          @dragleave="dragging = false"
          @drop.prevent="onDrop"
          @animationend="flash = false"
        >
          <Seg v-model="scopeModel" variant="soft" label="搜索范围" hide-label-on-mobile :options="[['site', '站内', 'grid'], ['github', 'GitHub', 'github']]" class="self-start max-sm:hidden">
            <template #extra="{ option }"><Icon v-if="option[0] === 'github' && !authState.user" name="lock" :size="11" class="text-mute" /></template>
          </Seg>
          <span class="sic ml-1 shrink-0 self-center text-mute"><Icon name="search" :size="18" /></span>
          <label for="search" class="sr-only">{{ scope === 'github' ? '搜索 GitHub、收录项目' : '搜索本站' }}</label>
          <textarea
            v-if="scope === 'github'"
            id="search"
            ref="input"
            v-model="keyword"
            rows="1"
            enterkeyhint="search"
            class="min-w-0 flex-1 resize-none self-center border-0 bg-transparent py-2 text-[15px] leading-6 text-ink outline-none placeholder:text-mute focus-visible:outline-none"
            :placeholder="placeholder"
            @keydown.enter="onEnter"
          />
          <textarea
            v-else
            id="search"
            ref="input"
            v-model="keyword"
            rows="1"
            enterkeyhint="search"
            autocomplete="off"
            class="min-w-0 flex-1 resize-none self-center border-0 bg-transparent py-1 text-[15px] leading-6 text-ink outline-none placeholder:text-mute focus-visible:outline-none"
            :placeholder="placeholder"
            @keydown.enter="onEnter"
            @focus="assistOpen = true"
            @click="assistOpen = true"
          />
          <!-- v3.3.31 一键清空；v3.3.32 始终上下居中，和相机、放大镜同一水平线（不再跟随最后一行） -->
          <button
            v-if="keyword"
            type="button"
            class="clear-kw grid h-7 w-7 shrink-0 cursor-pointer place-items-center self-center"
            aria-label="清空输入"
            @mousedown.prevent
            @click="clearKeyword"
          ><span class="grid h-[18px] w-[18px] place-items-center rounded-full bg-ink/25 text-white transition-colors hover:bg-ink/40"><Icon name="x" :size="12" /></span></button>
          <span class="kbd hidden self-center md:inline-block" :class="{ press: kbdPress }">Ctrl K</span>
          <button type="button" class="grid h-10 w-10 shrink-0 cursor-pointer place-items-center rounded-[7px] text-ink-2 transition-colors hover:bg-hover hover:text-brand" title="截图识别 / 上传 .md .txt" aria-label="截图识别" @click="pickFile">
            <Icon name="camera" :size="18" />
          </button>
          <input ref="fileInput" type="file" accept="image/*,.md,.markdown,.txt,text/plain,text/markdown" class="hidden" @change="onPickFile" />
          <button v-magnet type="submit" class="btn-primary h-10 shrink-0 sm:h-10" :disabled="scope === 'github' && (!keyword.trim() || github?.busy)">
            <span>{{ scope === 'github' && github?.busy ? '处理中' : '搜索' }}</span><Icon name="arrow-right" :size="14" class="i-arrow max-[479px]:hidden" />
          </button>
        </form>
          <SearchAssist v-if="assistOpen && scope === 'site'" :q="keyword" @pick="pickSuggestion" @open="openSuggestion" />
        </div>
      </div>
    </section>

    <!-- GitHub：搜索 / 收录 -->
    <div v-if="ghMounted" v-show="scope === 'github'" class="mx-auto max-w-[1100px] px-4 pt-4 pb-10 md:px-6">
      <div class="flex justify-end"><CompareModeToggle /></div>
      <GithubPanel ref="github" @example="(t) => ((keyword = t), nextTick(() => input?.focus()))" @pick-file="pickFile" />
    </div>

    <!-- 站内：左分类 / 中列表 / 右榜单 -->
    <!-- v3.3.35 显式按范围判断：GitHub 面板改成 v-if="ghMounted" 后，原来的 v-else 在切过一次 GitHub 后永远不成立，站内变空白 -->
    <div v-if="scope === 'site'" class="home-shell mx-auto max-w-[1440px] px-4 pt-4 pb-10 md:px-6 md:pt-5">
      <aside class="home-side hidden min-[1100px]:sticky min-[1100px]:top-[76px] min-[1100px]:block">
        <div class="panel">
          <div class="flex items-center justify-between border-b border-line-2 px-3.5 py-3"><span class="cap">分类</span><span class="cap">{{ tree.length }}</span></div>
          <nav ref="sideNav" class="relative flex flex-col p-1.5" aria-label="分类筛选">
            <span class="side-thumb pointer-events-none absolute inset-x-1.5 top-0 rounded-[5px] bg-brand-soft" :style="sideThumb" />
            <button class="side-btn rp" :aria-current="!filters.category" @click="pickCategory('')">
              <Icon name="grid" :size="14" class="ico" />全部条目<b>{{ allCount }}</b>
            </button>
            <div class="mx-1 my-1.5 h-px bg-line-2" />
            <template v-for="g in tree" :key="g.code">
              <button class="side-btn rp" :aria-current="filters.category === g.code" @click="pickCategory(g.code)">
                <Icon :name="groupStyle(g.code).icon" :size="14" class="ico" />{{ g.name }}<b>{{ g.item_count }}</b>
              </button>
              <div v-if="activeGroup?.code === g.code" class="sub-list flex flex-col pb-1">
                <button v-for="c in g.children" :key="c.code" class="side-btn sub rp" :aria-current="filters.category === c.code" @click="pickCategory(c.code)">
                  {{ c.name }}<b>{{ c.item_count }}</b>
                </button>
              </div>
            </template>
          </nav>
        </div>
      </aside>

      <!-- 手机 / 平板：分类横条 -->
      <div class="home-chips min-[1100px]:hidden">
        <div ref="chips" class="scrollbar-none relative -mx-4 flex gap-2 overflow-x-auto px-4 py-0.5" role="group" aria-label="分类筛选">
          <span class="chip-thumb pointer-events-none absolute top-0.5 left-0 h-[calc(100%-4px)] rounded-full bg-brand shadow-[0_6px_14px_-8px_rgb(30_86_214/0.9)]" :style="chipThumb" />
          <button class="chip rp" :aria-pressed="!activeGroup" @click="pickCategory('')">全部 {{ allCount }}</button>
          <button v-for="g in tree" :key="g.code" class="chip rp" :aria-pressed="activeGroup?.code === g.code" @click="pickCategory(g.code)">{{ g.name }}</button>
        </div>
        <div v-if="activeGroup" class="scrollbar-none -mx-4 mt-2 flex gap-1.5 overflow-x-auto px-4">
          <button
            v-for="c in activeGroup.children"
            :key="c.code"
            class="h-7 shrink-0 cursor-pointer rounded-full px-2.5 text-[12px] transition-colors duration-300"
            :class="filters.category === c.code ? 'bg-brand-soft font-medium text-brand' : 'text-ink-2 hover:bg-hover'"
            @click="pickCategory(filters.category === c.code ? activeGroup.code : c.code)"
          >{{ c.name }}<span class="ml-1 font-mono text-[10.5px] text-mute">{{ c.item_count }}</span></button>
        </div>
      </div>

      <!-- 今日增速 -->
      <section v-reveal="1" class="home-movers panel" :class="{ in: rankIn }" aria-label="增速榜">
        <div class="flex items-center justify-between gap-2 border-b border-line-2 px-3.5 py-2.5">
          <span class="cap">{{ period === 'daily' ? '今日增速' : '近 7 天增速' }} Top 6</span>
          <Seg v-model="period" variant="mini" label="榜单周期" :options="[['daily', '日榜'], ['weekly', '周榜']]" />
        </div>
        <ol class="rank-list m-0 list-none p-1.5">
          <li v-for="(e, i) in moverList" :key="e.item.id">
            <RouterLink :to="{ path: `/items/${e.item.id}`, query: route.query }" class="rank-row">
              <span class="n">{{ String(i + 1).padStart(2, '0') }}</span>
              <span class="min-w-0">
                <b class="block truncate text-[13px] leading-[18px] font-medium">{{ e.item.name }}</b>
                <span class="block truncate text-[11px] leading-4 text-mute">{{ e.item.category?.name }} · ★ {{ formatStars(e.stars_end) }}</span>
              </span>
              <span class="text-right font-mono text-xs font-medium whitespace-nowrap text-brand tabular-nums">+{{ e.stars_delta.toLocaleString('en-US') }}</span>
              <span class="meter"><i :style="{ '--w': `${Math.max(6, Math.round((e.stars_delta / maxDelta) * 100))}%`, transitionDelay: `${i * 80}ms` }" /></span>
            </RouterLink>
          </li>
          <li v-if="movers[period] && !moverList.length" class="px-2 py-6 text-center text-[12.5px] text-mute">还没有{{ period === 'daily' ? '日' : '周' }}榜数据</li>
          <li v-if="!movers[period]" class="space-y-2 p-1"><div v-for="n in 4" :key="n" class="skeleton-bar h-9 rounded-md" /></li>
        </ol>
      </section>

      <!-- 列表 -->
      <section class="home-main min-w-0" aria-label="条目列表">
        <div class="mb-3.5 flex flex-wrap items-center gap-2">
          <Transition name="ttl" mode="out-in"><span :key="title" class="mr-1 text-base font-semibold tracking-[-0.01em]">{{ title }}</span></Transition>
          <!-- v3.3 订阅当前分类的上新 -->
          <button
            v-if="activeGroup"
            class="sub-btn inline-flex h-8 cursor-pointer items-center gap-1 rounded-full border px-2.5 text-[12.5px] transition-colors duration-300"
            :data-flash="subFlash || null"
            :class="isSubscribed(filters.category) ? 'border-brand bg-brand-soft text-brand' : 'border-line bg-white/70 text-ink-2 hover:border-brand hover:text-brand'"
            @click="toggleSub(filters.category, title)"
          ><Icon :name="isSubscribed(filters.category) ? 'check' : 'bell'" :size="13" />{{ isSubscribed(filters.category) ? '已订阅' : '订阅上新' }}</button>
          <Seg :model-value="filters.sort" label="排序" :options="SORTS" @update:model-value="(v) => setQuery({ sort: v })" />
          <Seg :model-value="filters.source" label="来源" :options="SOURCES" @update:model-value="(v) => setQuery({ source: v })" />
          <!-- v3.3.10 手机上紧跟在来源后面，和它排在同一行 -->
          <CompareModeToggle class="max-sm:order-1" />
          <div v-if="kinds.length" class="scrollbar-none max-w-full overflow-x-auto max-sm:order-2 max-sm:-mx-4 max-sm:w-[calc(100%+2rem)] max-sm:max-w-none max-sm:px-4">
            <Seg :model-value="filters.kind" variant="soft" label="使用类型" class="w-max" :options="kindOptions" @update:model-value="(v) => setQuery({ kind: v })" />
          </div>
          <span class="cap ml-auto max-sm:hidden">{{ filters.q ? `${sem ? '语义' : '名称'}匹配 ` : '' }}{{ shown.length }} / {{ shownTotal }}</span>
        </div>

        <div v-if="meta?.untranslated && isAdminUser()" class="mb-3 flex flex-wrap items-center gap-2 rounded-lg border border-warn/25 bg-warn-soft px-3.5 py-2.5 text-[13px] text-warn">
          <Icon name="alert" :size="15" />
          <span v-if="meta.ai_enabled" class="flex-1">有 {{ meta.untranslated }} 个条目还是英文原文</span>
          <span v-else class="flex-1">尚未配置 AI 接口，{{ meta.untranslated }} 个条目的英文内容无法翻译成中文</span>
          <button v-if="meta.ai_enabled" class="btn-primary btn-sm" @click="translateAll">一键中文化</button>
        </div>

        <Transition name="list-fade">
          <div v-if="filters.q && (sem || semLoading || exactOnly)" class="mb-3 flex flex-wrap items-center gap-2 rounded-lg border border-brand/15 bg-brand-soft px-3.5 py-2.5 text-[13px]">
            <template v-if="semLoading">
              <Icon name="sparkles" :size="15" class="animate-pulse text-brand" /><span class="text-ink-2">正在按语义查找「{{ filters.q }}」…</span>
            </template>
            <template v-else-if="sem">
              <Icon name="sparkles" :size="15" class="text-brand" :class="{ 'animate-pulse': aiRefining }" />
              <span v-if="aiRefining" class="min-w-0 flex-1 text-ink-2">已找到 {{ sem.items.length }} 个，AI 正在理解需求并排序…</span>
              <span v-else-if="sem.understanding" class="min-w-0 flex-1"><b class="font-semibold text-brand">AI 理解为：</b>{{ sem.understanding }}</span>
              <span v-else class="min-w-0 flex-1 text-ink-2">按语义相似度排序</span>
              <AiTag v-if="sem.understanding || aiRefining" :model="sem.ai_model" />
              <button class="cursor-pointer text-[12.5px] text-brand hover:underline" @click="setQuery({ exact: '1' })">只看名称匹配</button>
            </template>
            <template v-else>
              <Icon name="search" :size="15" class="text-mute" /><span class="flex-1 text-ink-2">正在显示名称匹配的结果</span>
              <button class="cursor-pointer text-[12.5px] text-brand hover:underline" @click="setQuery({ exact: '' })">用 AI 语义搜索</button>
            </template>
          </div>
        </Transition>

        <p v-if="error" class="mb-3 flex items-center gap-2 rounded-lg bg-danger-soft p-3 text-sm text-danger" role="alert"><Icon name="alert" :size="16" />{{ error }}</p>

        <!-- 首次加载：骨架屏 -->
        <div v-if="firstLoad" class="home-grid" aria-busy="true">
          <div v-for="n in 8" :key="n" class="skel"><div class="skeleton-bar aspect-[16/9.5] sm:aspect-[16/8.5]" /><div class="space-y-2 p-3"><div class="skeleton-bar h-2.5 w-[55%] rounded-[3px]" /><div class="skeleton-bar h-2.5 w-[35%] rounded-[3px]" /><div class="skeleton-bar h-2.5 rounded-[3px]" /><div class="skeleton-bar h-2.5 w-4/5 rounded-[3px]" /></div></div>
        </div>

        <Transition v-else name="list-fade" mode="out-in">
          <TransitionGroup :key="listVersion" tag="div" name="reorder" class="home-grid">
            <ItemCard v-for="(it, i) in shown" :key="it.id" :item="it" :index="i % 6" dense />
            <div v-if="!shown.length && !error && !semLoading" class="col-span-full flex flex-col items-center gap-3 rounded-lg border border-dashed border-line bg-panel px-6 py-12 text-center">
              <b class="text-[15px] text-ink">{{ filters.q || filters.category || filters.source || filters.kind ? '没有符合条件的条目' : '还没有收录任何条目' }}</b>
              <button v-if="filters.q" class="btn-primary btn-sm max-w-full" @click="(keyword = filters.q), setScope('github')"><Icon name="github" :size="15" class="shrink-0" /><span class="min-w-0 truncate">去 GitHub 找「{{ filters.q }}」</span></button>
              <button v-else class="btn-primary btn-sm" @click="goCollect(router)"><Icon name="plus" :size="15" class="i-plus" />收录</button>
              <!-- v3.3 搜不到时的推荐：最近星标涨得最快的几个 -->
              <div v-if="filters.q && moverList.length" class="mt-4 w-full max-w-[520px] text-left">
                <p class="cap mb-2 text-center">看看最近大家在关注的</p>
                <div class="grid gap-1.5 sm:grid-cols-2">
                  <RouterLink v-for="(e, i) in moverList.slice(0, 6)" :key="e.item.id" v-reveal="i" :to="{ path: `/items/${e.item.id}`, query: route.query }" class="flex min-w-0 items-center gap-2.5 rounded-[8px] border border-line bg-white/70 px-3 py-2 transition-[border-color,transform] duration-300 hover:-translate-y-px hover:border-brand">
                    <span class="font-mono text-[12px] font-semibold text-brand">{{ String(i + 1).padStart(2, '0') }}</span>
                    <span class="min-w-0 flex-1">
                      <b class="block truncate text-[13px] font-medium">{{ e.item.name }}</b>
                      <span class="block truncate text-[11.5px] text-mute">{{ e.item.summary || e.item.category?.name }}</span>
                    </span>
                  </RouterLink>
                </div>
              </div>
            </div>
          </TransitionGroup>
        </Transition>

        <div v-if="!sem && items.length && !firstLoad" ref="moreEl" class="mt-4 flex justify-center">
          <button v-if="items.length < total" class="btn-glass w-full sm:w-auto" :disabled="loading" @click="more">
            <span v-if="loading" class="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-r-transparent" />
            <span>{{ loading ? '加载中' : '加载更多' }}</span>
          </button>
        </div>
      </section>

      <div class="home-extra flex flex-col gap-4">
        <section v-reveal="2" class="panel" aria-label="分类分布">
          <div class="flex items-center justify-between border-b border-line-2 px-3.5 py-3"><span class="cap">分类分布</span></div>
          <div class="bars px-3.5 pt-2 pb-3" :class="{ in: tree.length }">
            <button v-for="g in tree" :key="g.code" class="bar-row" :class="{ on: activeGroup?.code === g.code }" @click="pickFromBars(g.code)">
              <span class="truncate text-left">{{ g.name }}</span>
              <i><em :style="{ '--w': `${Math.max(2, Math.round((g.item_count / maxGroup) * 100))}%` }" /></i>
              <b>{{ g.item_count }}</b>
            </button>
          </div>
        </section>
        <section v-reveal="3" class="panel" aria-label="最新收录">
          <div class="flex items-center justify-between border-b border-line-2 px-3.5 py-3"><span class="cap">最新收录</span><span v-if="meta?.today_new" class="cap">今日 +{{ meta.today_new }}</span></div>
          <ul class="m-0 list-none p-1.5">
            <li v-for="(it, i) in fresh" :key="it.id">
              <RouterLink :to="{ path: `/items/${it.id}`, query: route.query }" class="flex gap-2.5 rounded-[5px] p-2 text-xs leading-[18px] transition-[background-color,transform] duration-300 ease-[var(--ease-spring)] hover:translate-x-[3px] hover:bg-hover">
                <span class="w-9 shrink-0 font-mono text-[11px] text-brand">{{ hm(it.collected_at) }}</span>
                <span class="min-w-0 flex-1">
                  <span class="flex min-w-0 items-center gap-1.5"><b class="min-w-0 truncate font-medium">{{ it.name }}</b><span v-if="i === 0" class="new-badge shrink-0 !ml-0">NEW</span></span>
                  <span class="block truncate text-[11px] text-mute">{{ it.category?.group_name }} / {{ it.category?.name }}</span>
                </span>
              </RouterLink>
            </li>
          </ul>
        </section>
      </div>
    </div>

    <!-- 手机紧凑搜索条 -->
    <Transition name="mini-bar">
      <form
        v-if="mini"
        class="glass-strong fixed inset-x-0 z-20 flex items-center gap-2 border-x-0 border-t-0 px-3 py-2 sm:hidden"
        :style="{ top: `${headerH}px` }"
        role="search"
        @submit.prevent="onSubmit"
      >
        <div class="relative min-w-0 flex-1">
          <span class="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-mute"><Icon :name="scope === 'github' ? 'github' : 'search'" :size="16" /></span>
          <input
            v-model="keyword"
            type="search"
            enterkeyhint="search"
            class="field h-10 pl-9 text-[14px]"
            :placeholder="scope === 'github' ? '搜索 GitHub，回车搜索' : '搜索本站'"
            :aria-label="scope === 'github' ? '搜索 GitHub' : '搜索本站'"
          />
        </div>
        <button v-if="scope === 'site'" type="button" class="btn-glass btn-sm h-10 shrink-0" @click="toFilters">
          <Icon name="layers" :size="15" />筛选<span v-if="activeFilters" class="grid h-4 min-w-4 place-items-center rounded-full bg-brand px-1 text-[10.5px] font-bold text-white">{{ activeFilters }}</span>
        </button>
        <button v-else type="submit" class="btn-primary btn-sm h-10 shrink-0" :disabled="!keyword.trim()">搜索</button>
      </form>
    </Transition>

    <!-- 详情抽屉 -->
    <RouterView v-slot="{ Component }">
      <Transition name="sheet">
        <component :is="Component" v-if="Component && ownRoute" />
      </Transition>
    </RouterView>
  </div>
</template>

<style scoped>
/* v3.3.31 一键清空：按下缩放；叉号线条加粗 */
.clear-kw:active > span {
  transform: scale(0.88);
}
.clear-kw > span {
  transition: transform 0.15s, background-color 0.2s;
}
.clear-kw :deep(svg) {
  stroke-width: 2.6;
}
/* 三栏：手机按「分类条 → 列表 → 增速榜 → 分布 / 最新」排（v3.2 增速榜挪到列表下面，和小程序一致）；≥1100 左分类、中列表、右榜单 */
.home-shell {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  grid-template-areas: 'chips' 'main' 'movers' 'extra';
  gap: 16px;
}
@media (min-width: 1100px) {
  .home-shell {
    grid-template-columns: 216px minmax(0, 1fr) 280px;
    grid-template-rows: auto 1fr;
    grid-template-areas: 'side main movers' 'side main extra';
    gap: 24px;
    align-items: start;
  }
}
@media (min-width: 1340px) {
  .home-shell {
    grid-template-columns: 232px minmax(0, 1fr) 300px;
  }
}
.home-side { grid-area: side; }
.home-chips { grid-area: chips; min-width: 0; }
.home-movers { grid-area: movers; }
.home-main { grid-area: main; }
.home-extra { grid-area: extra; }

.home-grid {
  display: grid;
  gap: 8px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}
@media (min-width: 640px) {
  .home-grid {
    grid-template-columns: repeat(auto-fill, minmax(210px, 1fr));
    gap: 14px;
  }
}
.skel {
  background: var(--color-panel);
  border: 1px solid var(--color-line);
  border-radius: 8px;
  overflow: hidden;
}

/* 指标：悬停时底部画一条线 */
.stat::after {
  content: '';
  position: absolute;
  left: 10px;
  right: 10px;
  bottom: 0;
  height: 2px;
  background: var(--color-brand);
  transform: scaleX(0);
  transform-origin: 0 50%;
  transition: transform 0.45s var(--ease-out-expo);
}
.stat:hover::after {
  transform: none;
}

/* 左栏 */
.side-thumb {
  transition: transform 0.5s var(--ease-spring), height 0.4s var(--ease-out-expo), opacity 0.3s;
}
.side-thumb::before {
  content: '';
  position: absolute;
  left: 0;
  top: 7px;
  bottom: 7px;
  width: 2px;
  border-radius: 2px;
  background: var(--color-brand);
}
.side-btn {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 8px;
  border-radius: 5px;
  font-size: 13px;
  line-height: 20px;
  color: var(--color-ink-2);
  text-align: left;
  cursor: pointer;
  transition: color 0.25s var(--ease-out-expo), padding 0.35s var(--ease-out-expo);
}
.side-btn:hover {
  color: var(--color-ink);
  padding-left: 12px;
}
.side-btn b {
  margin-left: auto;
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 400;
  color: var(--color-mute);
}
.side-btn[aria-current='true'] {
  color: var(--color-brand);
  font-weight: 600;
}
.side-btn[aria-current='true'] b {
  color: var(--color-brand);
}
.side-btn.sub {
  padding: 5px 8px 5px 30px;
  font-size: 12.5px;
}
.side-btn.sub:hover {
  padding-left: 34px;
}
.side-btn .ico {
  color: var(--color-mute);
  transition: transform 0.4s var(--ease-spring), color 0.3s;
}
.side-btn:hover .ico {
  transform: scale(1.2);
}
.side-btn[aria-current='true'] .ico {
  color: var(--color-brand);
}
.sub-list {
  animation: pop 0.4s var(--ease-out-expo);
}

/* 分类横条 */
.chip-thumb {
  transition: transform 0.5s var(--ease-spring), width 0.45s var(--ease-out-expo), opacity 0.3s;
}
.chip {
  position: relative;
  z-index: 1;
  flex: none;
  white-space: nowrap;
  font-size: 12px;
  line-height: 18px;
  color: var(--color-ink-2);
  border: 1px solid var(--color-line);
  background: rgb(255 255 255 / 0.6);
  border-radius: 999px;
  padding: 5px 11px;
  cursor: pointer;
  transition: color 0.3s var(--ease-out-expo), border-color 0.3s, transform 0.3s var(--ease-spring);
}
.chip:active {
  transform: scale(0.94);
}
.chip[aria-pressed='true'] {
  color: #fff;
  border-color: transparent;
  background: transparent;
}

/* 增速榜 */
.rank-row {
  display: grid;
  grid-template-columns: 20px minmax(0, 1fr) auto;
  align-items: center;
  gap: 4px 10px;
  padding: 8px;
  border-radius: 5px;
  transition: background-color 0.25s var(--ease-out-expo), transform 0.35s var(--ease-spring);
}
.rank-row:hover {
  background: var(--color-hover);
  transform: translateX(3px);
}
.rank-row .n {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--color-mute);
  font-variant-numeric: tabular-nums;
  transition: color 0.25s;
}
.rank-list li:nth-child(-n + 3) .n,
.rank-row:hover .n {
  color: var(--color-brand);
  font-weight: 600;
}
.meter {
  grid-column: 2 / 4;
  height: 3px;
  border-radius: 2px;
  background: var(--color-line-2);
  overflow: hidden;
}
.meter i {
  display: block;
  height: 100%;
  width: 0;
  border-radius: 2px;
  background: linear-gradient(90deg, var(--color-sky), var(--color-brand), var(--color-sky));
  background-size: 200% 100%;
  transition: width 1.1s var(--ease-out-expo);
  animation: flow 3s linear infinite;
}
.home-movers.in .meter i {
  width: var(--w);
}
@media (max-width: 1099px) {
  .rank-list {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  }
}

/* 分类分布 */
.bar-row {
  display: grid;
  width: 100%;
  grid-template-columns: 76px 1fr 32px;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  line-height: 16px;
  color: var(--color-ink-2);
  padding: 4px 0;
  cursor: pointer;
  transition: color 0.25s;
}
.bar-row:hover,
.bar-row.on {
  color: var(--color-brand);
}
.bar-row i {
  display: block;
  height: 6px;
  border-radius: 3px;
  background: var(--color-line-2);
  overflow: hidden;
}
.bar-row i em {
  display: block;
  height: 100%;
  width: 0;
  background: var(--color-brand);
  border-radius: 3px;
  transition: width 1s var(--ease-out-expo), background-color 0.3s;
}
.bar-row:hover i em {
  background: var(--color-sky);
}
.bars.in i em {
  width: var(--w);
}
.bar-row b {
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 400;
  color: var(--color-mute);
  text-align: right;
}

/* 标题切换 */
.ttl-enter-active,
.ttl-leave-active {
  transition: opacity 0.22s, transform 0.35s var(--ease-out-expo);
}
.ttl-enter-from,
.ttl-leave-to {
  opacity: 0;
  transform: translateY(6px);
}
.sub-btn[data-flash] {
  animation: subflash 0.8s ease-in-out 3;
}
@keyframes subflash {
  50% {
    box-shadow: 0 0 0 6px rgb(30 86 214 / 0.22);
    border-color: var(--color-brand);
    color: var(--color-brand);
  }
}
</style>
