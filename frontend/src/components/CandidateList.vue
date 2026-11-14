<script setup>
import { useItemLink } from '../composables/itemLink'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { api, formatStars } from '../api'
import { kindStyle } from '../categoryStyle'
import { compareState, fromCandidate, inCompare, toggleCompare } from '../composables/compare'
import { meta } from '../composables/meta'
import { toast } from '../composables/toast'
import { addPending, bumpTasks, removePending } from '../composables/tasks'
import CheckBox from './CheckBox.vue'
import Icon from './Icon.vue'
import JoinBar from './JoinBar.vue'

// 搜索添加 / 长文识别的结果列表：勾选后加入。state：matched 可加入 / existing 已收录 / unmatched 没找到 / closed 非开源 / resolving 对应中
const itemLink = useItemLink()
const props = defineProps({
  jobId: { type: Number, required: true },
  candidates: { type: Array, default: () => [] },
  mode: { type: String, default: 'search' }, // search / text
  autoSelect: { type: Boolean, default: false }, // v3.3.7：默认都不勾选，用户自己挑（只选一个时不用先全选再取消）
  preview: Boolean, // AI 还在排序时先展示的原始结果：只能看和对比，排序完成后才能勾选加入（加入按序号对应）
})
const emit = defineEmits(['manual', 'adopt'])
const router = useRouter()
const route = useRoute()
// 已收录的条目：点名称在当前页弹出详情抽屉（保留搜索结果）

// 每一行左侧图标的提示：鼠标放上去说明为什么不能勾选
const STATE_TIP = {
  existing: '已收录，点名称查看详情',
  closed: '非开源产品，没有 GitHub 仓库，可以手动收录',
  unmatched: '没找到对应的 GitHub 仓库',
  resolving: '正在对应 GitHub 仓库',
  importing: '正在加入本站…',
}
function tipOf(c) {
  if (props.preview && c.state === 'matched') return 'AI 正在按相关度排序，排好后就能勾选加入'
  return STATE_TIP[c.state] || ''
}

// 「加入」栏：列表在屏幕里时固定在视口底部，不用滑到最后才能点
const root = ref(null)
const onScreen = ref(false)
let io
onMounted(() => {
  io = new IntersectionObserver(([e]) => (onScreen.value = e.isIntersecting), { rootMargin: '0px 0px -80px 0px' })
  if (root.value) io.observe(root.value)
})
onBeforeUnmount(() => io?.disconnect())
const STAGES = ['正在核对仓库…', 'AI 正在读取文档…', 'AI 正在分析分类…', '马上就好…']
const stage = ref('')

const selected = ref(new Set())
const filter = ref('all')
const posting = ref(false) // 「加入」请求正在发出
const openSearch = ref(null)
const searchQ = ref('')
const searchRes = ref(null)
const overrides = ref({}) // 手动改过对应仓库的条目：index → patch

const VIA = { link: '原文链接', github: 'GitHub', fuzzy: 'GitHub · 已纠正拼写', search: 'GitHub 搜索', 'skills.sh': 'skills.sh', ai: 'AI 结合上下文挑选', manual: '手动指定', library: '库内同名' }
const kindName = (k) => meta.data?.kinds?.find((x) => x.key === k)?.name

const list = computed(() => props.candidates.map((c, i) => ({ ...c, ...(overrides.value[i] || {}), i })))
const isUncertain = (c) => c.state === 'matched' && c.uncertain
const counts = computed(() => {
  const n = { all: list.value.length, matched: 0, uncertain: 0, existing: 0, unmatched: 0, closed: 0, resolving: 0, importing: 0 }
  list.value.forEach((c) => {
    n[c.state] = (n[c.state] || 0) + 1
    if (isUncertain(c)) n.uncertain++
  })
  return n
})
const FILTERS = computed(() =>
  [
    ['all', '全部'],
    ['matched', '可加入'],
    ['uncertain', '需核对'],
    ['existing', '已收录'],
    ['unmatched', '没找到'],
    ['closed', '非开源'],
  ].filter(([k]) => k === 'all' || counts.value[k]),
)
const visible = computed(() =>
  list.value.filter((c) => filter.value === 'all' || (filter.value === 'uncertain' ? isUncertain(c) : c.state === filter.value)),
)
const selectable = computed(() => list.value.filter((c) => c.state === 'matched').map((c) => c.i))
const picked = computed(() => [...selected.value].filter((i) => list.value[i]?.state === 'matched'))
const allPicked = computed(() => selectable.value.length > 0 && selectable.value.every((i) => selected.value.has(i)))

// 新出现的可加入条目：搜索结果按相关度自动勾选高分的；长文识别勾选有把握的
const seen = new Set()
watch(
  list,
  (l) => {
    const s = new Set(selected.value)
    for (const c of l) {
      if (c.state !== 'matched' || seen.has(c.i)) continue
      seen.add(c.i)
      if (!props.autoSelect) continue
      const good = props.mode === 'search' ? (c.score ?? 0) >= 80 : !c.uncertain
      if (good) s.add(c.i)
    }
    selected.value = s
  },
  { immediate: true },
)

// AI 智能对比模式下，勾选框和整行点击都用来选「对比」（已收录的也能比）；否则用来选「加入本站」
// v3.3.7：正在加入本站的行也能勾选对比（对比和加入是两套逻辑）
const comparable = (c) => props.mode === 'search' && !!c.full_name && ['matched', 'existing', 'importing'].includes(c.state)
const compareOn = computed(() => compareState.mode && props.mode === 'search')

function toggle(c) {
  if (compareOn.value) {
    if (comparable(c)) toggleCompare(fromCandidate(c))
    return
  }
  // v3.1：点了不能勾选的条目，直接说明原因（原来只有鼠标悬停提示，手机上看不到）
  if (c.state !== 'matched' || props.preview) return tipOf(c) && toast(tipOf(c), 'info', 2600)
  const s = new Set(selected.value)
  s.has(c.i) ? s.delete(c.i) : s.add(c.i)
  selected.value = s
}
function toggleAll() {
  selected.value = allPicked.value ? new Set() : new Set(selectable.value)
}

function repoLabel(c) {
  if (!c.match) return ''
  return c.sub_path ? `${c.match.full_name} / ${c.sub_path.split('/').pop()}` : c.match.full_name
}

// ---- 手动更正 ----
function startSearch(c) {
  openSearch.value = openSearch.value === c.i ? null : c.i
  searchQ.value = c.name
  searchRes.value = null
  if (openSearch.value !== null) runSearch()
}
async function runSearch() {
  if (!searchQ.value.trim()) return
  searchRes.value = 'loading'
  try {
    searchRes.value = await api(`/api/uploads/search?q=${encodeURIComponent(searchQ.value.trim())}`)
  } catch {
    searchRes.value = []
  }
}
function choose(c, r) {
  overrides.value = {
    ...overrides.value,
    [c.i]: { match: r, via: 'manual', uncertain: false, state: 'matched', existing_item_id: null, sub_path: null, ...(r.skill_id ? { name: r.skill_id } : {}) },
  }
  selected.value = new Set(selected.value).add(c.i)
  openSearch.value = null
}

// 后台加入的进度：服务器每加好一个，就把那一行改成「已收录」（带条目 id），这里跟着任务轮询原地更新。
// v3.3.7：可以有多批同时在加入——加入中还能继续勾选别的行再点「加入」
const batches = ref([]) // [{ idx: [...], pid, ticker }]
const busy = computed(() => posting.value || batches.value.length > 0 || counts.value.importing > 0)
watch(
  () => props.candidates.map((c) => c.state).join(),
  () => {
    const finished = batches.value.filter((b) => !b.idx.some((i) => props.candidates[i]?.state === 'importing'))
    if (!finished.length) return
    batches.value = batches.value.filter((b) => !finished.includes(b))
    for (const b of finished) {
      const ok = b.idx.filter((i) => props.candidates[i]?.state === 'existing')
      b.idx.map((i) => props.candidates[i]).filter((c) => c?.import_error).forEach((c) => toast(c.import_error, 'error', 4500))
      removePending(b.pid)
      clearInterval(b.ticker)
      bumpTasks()
      if (ok.length) {
        toast(`已加入 ${ok.length} 个，AI 正在后台分析`, 'success', 3500)
        const id = props.candidates[ok[0]].existing_item_id
        if (ok.length === 1 && id && !batches.value.length) router.push(itemLink(id))
      }
    }
  },
)

async function doImport() {
  const idx = [...picked.value]
  const picks = idx.map((i) => {
    const c = list.value[i]
    return { full_name: c.match.full_name, name: c.name, sub_path: c.sub_path ?? null, kind: c.kind || '', index: i }
  })
  if (!picks.length || posting.value) return
  posting.value = true
  // v3.3.26 点了就清空这批勾选，加入栏随之收起；失败时恢复勾选方便重试
  const keep = new Set(selected.value)
  selected.value = new Set()
  // 接口要先核对仓库再建任务，可能要几秒：按钮和任务浮窗立即给反馈
  let k = 0
  stage.value = STAGES[0]
  const ticker = setInterval(() => (stage.value = STAGES[Math.min(++k, STAGES.length - 1)]), 1600)
  const pid = addPending(`加入 ${picks.length} 个条目`, `正在加入 ${picks.length} 个，AI 准备分析…`)
  try {
    const r = await api(`/api/finder/${props.jobId}/import`, { method: 'POST', body: { picks } })
    // 以服务器为准：清掉这几行的手动改动和勾选，交给任务轮询更新
    const o = { ...overrides.value }
    idx.forEach((i) => delete o[i])
    overrides.value = o
    batches.value = [...batches.value, { idx, pid, ticker }]
    emit('adopt', r.job)
  } catch (e) {
    toast(e.message, 'error')
    selected.value = new Set([...keep, ...selected.value])
    clearInterval(ticker)
    removePending(pid)
  } finally {
    posting.value = false
  }
}
</script>

<template>
  <div ref="root" class="pb-20">
    <div v-if="counts.all > 1" class="scrollbar-none -mx-1 flex gap-1.5 overflow-x-auto px-1 pb-1">
      <button
        v-for="f in FILTERS"
        :key="f[0]"
        class="flex h-8 shrink-0 cursor-pointer items-center gap-1 rounded-full px-3 text-[13px] transition-colors duration-300"
        :class="filter === f[0] ? 'bg-brand font-medium text-white' : 'border border-edge bg-white/60 text-ink-2 hover:bg-white'"
        @click="filter = f[0]"
      >{{ f[1] }}<span class="tabular-nums opacity-75">{{ counts[f[0]] }}</span></button>
    </div>

    <p v-if="compareOn" class="mt-2 flex items-center gap-1.5 px-1 text-[13px] text-brand">
      <span class="tag bg-brand text-white">AI 智能对比</span>勾选要对比的仓库（已收录的也可以），在底部对比栏开始对比
    </p>
    <div v-else-if="selectable.length > 1 && !preview" class="mt-2 flex cursor-pointer items-center gap-2 px-1 text-[13px] text-ink-2" @click="toggleAll">
      <CheckBox :checked="allPicked" label="全选可加入的" @toggle="toggleAll" />全选可加入的（{{ selectable.length }}）
    </div>

    <ul class="mt-2 space-y-2">
      <li
        v-for="c in visible"
        :key="c.i"
        v-reveal="c.i % 12"
        class="panel overflow-hidden transition-[background-color,box-shadow] duration-300"
        :class="(compareOn ? comparable(c) && inCompare(fromCandidate(c)) : selected.has(c.i) && c.state === 'matched') ? 'bg-white/85 ring-2 ring-brand/40' : ''"
      >
        <div class="flex gap-3 p-3" :class="(compareOn ? comparable(c) : c.state === 'matched' && !preview) ? 'cursor-pointer' : ''" @click="toggle(c)">
          <div class="flex w-7 shrink-0 flex-col items-center gap-1 pt-0.5">
            <CheckBox
              v-if="compareOn && comparable(c)"
              tone="compare"
              :checked="inCompare(fromCandidate(c))"
              :label="`对比 ${c.name}`"
              @toggle="toggle(c)"
            />
            <CheckBox v-else-if="!compareOn && !preview && c.state === 'matched'" :checked="selected.has(c.i)" :label="`选择 ${c.name}`" @toggle="toggle(c)" />
            <span v-else-if="preview && c.state === 'matched'" class="cursor-help text-mute" :title="tipOf(c)" @click.stop="toast(tipOf(c), 'info', 2600)" :aria-label="tipOf(c)"><Icon name="clock" :size="16" class="animate-pulse" /></span>
            <span v-else-if="c.state === 'resolving' || c.state === 'importing'" class="text-brand" :title="tipOf(c)" @click.stop="toast(tipOf(c), 'info', 2600)"><Icon name="refresh" :size="16" class="animate-spin" /></span>
            <span v-else-if="c.state === 'existing'" class="cursor-help text-ok" :title="tipOf(c)" @click.stop="toast(tipOf(c), 'info', 2600)"><Icon name="check" :size="18" /></span>
            <span v-else-if="c.state === 'closed'" class="cursor-help text-mute" :title="tipOf(c)" @click.stop="toast(tipOf(c), 'info', 2600)"><Icon name="lock" :size="16" /></span>
            <span v-else class="cursor-help text-warn" :title="tipOf(c)" @click.stop="toast(tipOf(c), 'info', 2600)" :aria-label="tipOf(c)"><Icon name="alert" :size="17" /></span>
            <span v-if="c.score != null" class="text-[11px] font-bold tabular-nums" :class="c.score >= 80 ? 'text-ok' : 'text-mute'" :title="`相关度 ${c.score}`">{{ c.score }}</span>
          </div>

          <div class="min-w-0 flex-1">
            <div class="flex flex-wrap items-center gap-x-1.5 gap-y-1">
              <RouterLink v-if="c.state === 'existing' && c.existing_item_id" :to="itemLink(c.existing_item_id)" class="font-semibold break-all text-ink underline-offset-4 hover:text-brand hover:underline" @click.stop>{{ mode === 'search' && c.match ? repoLabel(c) : c.name }}</RouterLink>
              <span v-else class="font-semibold break-all">{{ mode === 'search' && c.match ? repoLabel(c) : c.name }}</span>
              <span v-if="kindName(c.kind)" class="tag" :class="kindStyle(c.kind).cls">{{ kindName(c.kind) }}</span>
              <span v-if="mode === 'search' && c.stars != null" class="flex items-center gap-0.5 text-xs text-mute"><Icon name="star" :size="11" class="fill-amber-400 text-amber-400" />{{ formatStars(c.stars) }}</span>
              <span v-if="mode === 'search' && c.installs" class="text-xs text-mute">安装 {{ formatStars(c.installs) }}</span>
            </div>

            <!-- 搜索：AI 给的理由；长文：原文出处 -->
            <p v-if="c.reason" class="mt-1 text-[13px] leading-relaxed text-ink-2">{{ c.reason }}</p>
            <p v-else-if="mode === 'search' && c.description" class="mt-1 line-clamp-2 text-[13px] leading-relaxed text-ink-2">{{ c.description }}</p>
            <p v-if="mode === 'text' && c.description" class="mt-0.5 text-[13px] leading-relaxed text-ink-2">{{ c.description }}</p>
            <blockquote v-if="c.context" class="mt-1.5 border-l-2 border-brand/30 pl-2 text-[12.5px] leading-relaxed text-mute">“{{ c.context }}”</blockquote>

            <p v-if="c.state === 'importing'" class="mt-2 flex items-center gap-1.5 text-[12.5px] text-brand"><Icon name="sparkles" :size="13" class="animate-pulse" />正在加入本站…</p>
            <p v-if="c.import_error && c.state === 'matched'" class="mt-1.5 text-[12.5px] text-danger">{{ c.import_error }}</p>
            <div v-if="c.state === 'resolving'" class="skeleton-bar mt-2 h-7 w-3/4 rounded-lg" />
            <div v-else-if="c.match && mode === 'text'" class="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 rounded-xl bg-white/60 px-2.5 py-1.5 text-[12.5px]">
              <Icon name="github" :size="13" class="text-ink-2" />
              <a :href="c.match.html_url" target="_blank" rel="noopener" class="min-w-0 cursor-pointer font-medium break-all hover:text-brand" @click.stop>{{ repoLabel(c) }}</a>
              <span v-if="c.match.stars" class="flex items-center gap-0.5 text-mute"><Icon name="star" :size="11" class="fill-amber-400 text-amber-400" />{{ formatStars(c.match.stars) }}</span>
              <span v-if="c.uncertain" class="tag h-5 bg-warn-soft px-1.5 text-[11px] text-warn" :title="c.pick_reason">推测，请核对</span>
              <span v-else class="tag h-5 bg-white/80 px-1.5 text-[11px] text-mute" :title="c.pick_reason">{{ VIA[c.via] || c.via }}</span>
            </div>
            <a v-else-if="c.match" :href="c.match.html_url" target="_blank" rel="noopener" class="mt-1 inline-flex items-center gap-1 text-[12.5px] text-mute hover:text-brand" @click.stop>
              <Icon name="external-link" :size="12" />在 GitHub 查看
            </a>
            <p v-else-if="c.state === 'closed'" class="mt-2 text-[12.5px] text-mute">闭源产品，没有 GitHub 仓库</p>
            <p v-else-if="c.state === 'unmatched'" class="mt-2 text-[12.5px] text-warn">没找到对应的 GitHub 仓库</p>

            <div v-if="c.state !== 'resolving'" class="mt-2 flex flex-wrap items-center gap-3 text-[12.5px]" @click.stop>
              <RouterLink v-if="c.state === 'existing' && c.existing_item_id" :to="itemLink(c.existing_item_id)" class="tag cursor-pointer bg-ok-soft text-ok">已收录 · 查看</RouterLink>
              <span v-else-if="c.state === 'existing'" class="tag bg-ok-soft text-ok">已收录</span>
              <button v-if="mode === 'text'" class="cursor-pointer text-brand hover:underline" @click="startSearch(c)">
                {{ c.state === 'matched' ? '对应错了？换一个' : c.state === 'existing' ? '不是同一个？' : '手动搜索' }}
              </button>
              <button v-if="c.state === 'closed' || c.state === 'unmatched'" class="cursor-pointer text-brand hover:underline" @click="emit('manual', { name: c.name, homepage_url: c.homepage || '', summary: c.description || '' })">
                手动收录
              </button>
            </div>

            <div v-if="openSearch === c.i" class="mt-2" @click.stop>
              <form class="flex gap-2" @submit.prevent="runSearch">
                <input v-model="searchQ" class="field h-9 sm:h-9" :aria-label="`搜索 ${c.name} 的仓库`" />
                <button class="btn-glass btn-sm shrink-0"><Icon name="search" :size="15" />搜索</button>
              </form>
              <p v-if="searchRes === 'loading'" class="mt-2 text-xs text-mute">搜索中…</p>
              <ul v-else-if="searchRes?.length" class="mt-2 divide-y divide-line overflow-hidden rounded-xl border border-edge bg-white/70">
                <li v-for="r in searchRes" :key="r.full_name + (r.skill_id || '')">
                  <button class="flex w-full cursor-pointer items-center gap-2 px-3 py-2 text-left text-[13px] transition-colors duration-200 hover:bg-brand-soft" @click="choose(c, r)">
                    <span class="min-w-0 flex-1 truncate"><b class="font-medium">{{ r.full_name }}</b><span v-if="r.skill_id" class="text-mute"> / {{ r.skill_id }}</span></span>
                    <span class="shrink-0 text-xs text-mute">{{ r.installs ? `安装 ${formatStars(r.installs)}` : formatStars(r.stars) }}</span>
                  </button>
                </li>
              </ul>
              <p v-else-if="searchRes" class="mt-2 text-xs text-mute">没有搜到</p>
            </div>
          </div>
        </div>
      </li>
    </ul>
    <p v-if="counts.all && !visible.length" class="mt-3 text-center text-sm text-mute">这个分类下没有条目</p>

    <!-- v3.3.26 加入栏：只在有勾选时出现，点「加入」后收起，进度看右侧任务浮窗（与截图识别共用 JoinBar） -->
    <JoinBar :show="!compareOn && !preview && onScreen" :count="picked.length" :note="busy ? `另有 ${counts.importing} 个加入中` : ''" :posting="posting" @join="doImport" />
  </div>
</template>
