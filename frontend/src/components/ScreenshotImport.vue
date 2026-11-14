<script setup>
import { useItemLink } from '../composables/itemLink'
import CheckBox from './CheckBox.vue'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { api, authHeaders, formatStars, isCancelled } from '../api'
import { requireLogin } from '../composables/auth'
import { toast } from '../composables/toast'
import { addPending, bumpTasks, removePending } from '../composables/tasks'
import JoinBar from './JoinBar.vue'
import Icon from './Icon.vue'
import AiTag from './AiTag.vue'
import { compareState, fromCandidate, inCompare, isComparing, toggleCompare } from '../composables/compare'

const itemLink = useItemLink()
const router = useRouter()
const props = defineProps({ embedded: Boolean })

const fileInput = ref(null)
const previewUrl = ref('')
const dragging = ref(false)
const phase = ref('idle') // idle / recognizing / done / error
const error = ref('')
const result = ref(null)
const selected = ref(new Set())
const filter = ref('all')
const imgOpen = ref(false)
const importing = ref(false)
const openSearch = ref(null) // 正在手动搜索的条目序号
const searchQ = ref('')
const searchRes = ref(null)
let pollTimer

const KIND = { skill: 'Skill', model: '模型', tool: '工具', agent: '智能体', other: '其他' }
const VIA = { library: '库内同名', 'skills.sh': 'skills.sh', github: 'GitHub', fuzzy: 'GitHub · 已纠正拼写', search: 'GitHub 搜索', manual: '手动指定' }

const items = computed(() => result.value?.items || [])
const counts = computed(() => {
  const c = { all: items.value.length, matched: 0, existing: 0, unmatched: 0, resolving: 0 }
  items.value.forEach((it) => c[it.state]++)
  return c
})
const resolving = computed(() => counts.value.resolving > 0)
const FILTERS = computed(() => [
  ['all', '全部', counts.value.all],
  ['matched', '可加入', counts.value.matched],
  ['existing', '已收录', counts.value.existing],
  ['unmatched', '未匹配', counts.value.unmatched],
])
const visible = computed(() => items.value.map((it, i) => ({ it, i })).filter(({ it }) => filter.value === 'all' || it.state === filter.value))
const selectable = computed(() => items.value.map((it, i) => i).filter((i) => items.value[i].state === 'matched'))
const pickedCount = computed(() => [...selected.value].filter((i) => items.value[i]?.state === 'matched').length)
const allPicked = computed(() => selectable.value.length > 0 && selectable.value.every((i) => selected.value.has(i)))

// 库里同名、但来源（仓库 / Skill 目录）不同的条目：提示用户，不自动勾选
function sameNameOthers(it) {
  const seen = new Set()
  return (it.same_name || []).filter((x) => {
    const differs = !it.match || (x.repo || '').toLowerCase() !== it.match.full_name.toLowerCase() || (x.sub_path || '') !== (it.sub_path || '')
    const key = x.repo || x.name
    if (!differs || seen.has(key)) return false
    seen.add(key)
    return true
  })
}

function applyResult(data, autoSelect) {
  const before = result.value?.items || []
  result.value = data
  if (autoSelect) {
    // 刚对应上的条目自动勾选
    const s = new Set(selected.value)
    data.items.forEach((it, i) => {
      if (it.state === 'matched' && before[i]?.state !== 'matched' && before[i]?.via !== 'manual' && !sameNameOthers(it).length && !it.uncertain) s.add(i)
    })
    selected.value = s
  }
}

async function poll() {
  clearTimeout(pollTimer)
  if (!result.value) return
  try {
    const res = await fetch(`/api/uploads/${result.value.id}`, { headers: authHeaders() })
    if (res.ok) applyResult(await res.json(), true)
  } catch {}
  if (resolving.value) pollTimer = setTimeout(poll, 1200)
}

async function send(file) {
  if (!file) return
  if (!(await requireLogin('截图识别需要先登录'))) return
  if (!file.type.startsWith('image/')) return toast('请选择图片文件', 'error')
  if (file.size > 10 * 1024 * 1024) return toast('图片不能超过 10MB', 'error')
  URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = URL.createObjectURL(file)
  phase.value = 'recognizing'
  error.value = ''
  result.value = null
  selected.value = new Set()
  filter.value = 'all'
  const fd = new FormData()
  fd.append('file', file)
  try {
    const res = await fetch('/api/uploads', { method: 'POST', body: fd, headers: authHeaders() })
    const data = await res.json().catch(() => ({}))
    if (!res.ok) throw new Error(data.detail || `识别失败（${res.status}）`)
    applyResult(data, true)
    phase.value = 'done'
    poll()
  } catch (e) {
    error.value = e.message
    phase.value = 'error'
  }
}

function onPick(e) {
  send(e.target.files?.[0])
  e.target.value = ''
}
function onDrop(e) {
  dragging.value = false
  send(e.dataTransfer.files?.[0])
}
function onPaste(e) {
  const f = [...(e.clipboardData?.files || [])].find((x) => x.type.startsWith('image/'))
  if (f) send(f)
}

// AI 智能对比：打开后可勾选对应到仓库的条目（已收录的也可以）
const compareOn = computed(() => compareState.mode)
const compareEntry = (it) => fromCandidate({ name: it.name, full_name: it.match.full_name, sub_path: it.sub_path || '',
  existing_item_id: it.state === 'existing' ? it.existing_item_id : null, stars: it.match.stars ?? null, description: it.match.description || '' })

// v3.3.81 加入中 / 对比中的行：显示转圈、不能勾选，点一下或悬停提示原因
// 加入中和对比互不影响：加入中的条目照样可以勾选对比
const comparing = (it) => !!it.match?.full_name && ['matched', 'existing', 'importing'].includes(it.state) && isComparing(compareEntry(it))
const comparable = (it) => !!it.match?.full_name && ['matched', 'existing', 'importing'].includes(it.state) && !comparing(it)
const busyTip = (it) => (it.state === 'importing' ? '正在加入本站，加好后会变成「已收录」' : comparing(it) ? '正在对比中，完成后可在对比栏查看结果' : '')

function toggle(i) {
  const it = items.value[i]
  const blocked = compareOn.value ? comparing(it) : busyTip(it)
  if (blocked) return toast(compareOn.value ? '正在对比中，完成后可在对比栏查看结果' : busyTip(it), 'info', 2600)
  if (compareOn.value) {
    if (comparable(it)) toggleCompare(compareEntry(it))
    return
  }
  if (it.state !== 'matched') return
  const s = new Set(selected.value)
  s.has(i) ? s.delete(i) : s.add(i)
  selected.value = s
}
function toggleAll() {
  selected.value = allPicked.value ? new Set() : new Set(selectable.value)
}

// ---- 手动更正对应仓库 ----
function startSearch(i) {
  openSearch.value = openSearch.value === i ? null : i
  searchQ.value = items.value[i].name
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
function choose(i, r) {
  const it = items.value[i]
  // 手动指定后由导入接口判断是否重复；skills.sh 结果按名称在仓库里定位 Skill
  Object.assign(it, { match: r, via: 'manual', uncertain: false, state: 'matched', existing_item_id: null, sub_path: null, installs: r.installs ?? null })
  if (r.skill_id) it.name = r.skill_id
  selected.value = new Set(selected.value).add(i)
  openSearch.value = null
}

// 轮询后台加入的结果：网络偶尔失败就隔一会儿再试，最多等 15 分钟
async function waitImport(id) {
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
  throw new Error('加入时间较长，稍后可在「我的 → 提交」里查看结果')
}

// 加入完成：对应到条目的行改成「已收录」（能点开详情），没加进去的恢复成可加入
function settleJoining(idx, resolved) {
  const key = (fn, sub) => `${(fn || '').toLowerCase()}/${sub || ''}`
  const ids = new Map(resolved.map((r) => [key(r.full_name, r.sub_path), r.item_id]))
  idx.forEach((i) => {
    const it = items.value[i]
    if (!it || it.state !== 'importing') return
    const id = ids.get(key(it.match?.full_name, it.sub_path))
    Object.assign(it, id ? { state: 'existing', existing_item_id: id } : { state: 'matched' })
  })
}

async function doImport() {
  const picks = [...selected.value]
    .filter((i) => items.value[i]?.state === 'matched')
    .map((i) => ({ full_name: items.value[i].match.full_name, name: items.value[i].name, sub_path: items.value[i].sub_path ?? null }))
  if (!picks.length || importing.value) return
  importing.value = true
  // v3.3.26 点了就清空勾选、收起加入栏，进度放进右侧任务浮窗；失败时恢复勾选方便重试
  const keep = new Set(selected.value)
  const joining = [...selected.value].filter((i) => items.value[i]?.state === 'matched')
  joining.forEach((i) => (items.value[i].state = 'importing'))
  selected.value = new Set()
  const pid = addPending(`加入 ${picks.length} 个条目`, `正在加入 ${picks.length} 个，AI 准备分析…`)
  try {
    let data = await api(`/api/uploads/${result.value.id}/import`, { method: 'POST', body: { picks } })
    // v3.3.25 加入改到后台：20 秒内没加完先返回 queued，这里轮询识别记录，status 变成 imported 后读 import 字段
    if (data.queued) {
      toast(`正在加入 ${picks.length} 个，加好后会提示你`, 'info', 3000)
      data = await waitImport(result.value.id)
    }
    settleJoining(joining, data.resolved || [])
    data.errors.forEach((m) => toast(m, 'error', 4000))
    if (data.skipped.length) toast(`${data.skipped.length} 个已在库中，已跳过`, 'info', 3000)
    if (data.created.length) {
      toast(`已加入 ${data.created.length} 个条目，正在后台提炼`, 'success', 3500)
      if (data.created.length === 1) router.push(itemLink(data.created[0]))
    }
  } catch (e) {
    joining.forEach((i) => items.value[i]?.state === 'importing' && (items.value[i].state = 'matched'))
    selected.value = new Set([...keep, ...selected.value])
    if (!isCancelled(e)) toast(e.message, 'error')
  } finally {
    removePending(pid)
    bumpTasks()
    importing.value = false
  }
}

function reset() {
  clearTimeout(pollTimer)
  phase.value = 'idle'
  result.value = null
  URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = ''
}

function repoLabel(it) {
  if (!it.match) return ''
  return it.sub_path ? `${it.match.full_name} / ${it.sub_path.split('/').pop()}` : it.match.full_name
}

onMounted(() => !props.embedded && addEventListener('paste', onPaste))
defineExpose({ send, reset, phase })
onBeforeUnmount(() => {
  clearTimeout(pollTimer)
  removeEventListener('paste', onPaste)
  URL.revokeObjectURL(previewUrl.value)
})
</script>

<template>
  <div>
    <!-- 上传区 -->
    <div
      v-if="!embedded && (phase === 'idle' || phase === 'error')"
      class="flex cursor-pointer flex-col items-center gap-3 rounded-[12px] border-2 border-dashed px-6 py-12 text-center transition-all duration-300 ease-out-expo"
      :class="dragging ? 'scale-[1.01] border-brand bg-brand-soft' : 'border-brand/25 bg-white/40 hover:border-brand/50 hover:bg-white/60'"
      role="button"
      tabindex="0"
      @click="fileInput.click()"
      @keydown.enter="fileInput.click()"
      @dragover.prevent="dragging = true"
      @dragleave="dragging = false"
      @drop.prevent="onDrop"
    >
      <span class="float-y grid h-14 w-14 place-items-center rounded-2xl bg-brand text-white shadow-[0_10px_24px_-10px_rgb(30_86_214/0.7)]">
        <Icon name="image" :size="26" />
      </span>
      <p class="font-semibold">上传截图，AI 帮你找出里面的 Skill 和模型</p>
      <p class="text-sm text-ink-2">单个条目或整张榜单都可以 · 点击选择、拖进来，或 <kbd class="rounded-md border border-edge bg-white/80 px-1.5 text-xs">Ctrl</kbd> + <kbd class="rounded-md border border-edge bg-white/80 px-1.5 text-xs">V</kbd> 粘贴</p>
      <p class="text-xs text-mute">文章配图、榜单、推文、聊天记录都行 · PNG / JPG / WebP · 10MB 以内</p>
      <input ref="fileInput" type="file" accept="image/*" class="hidden" @change="onPick" />
    </div>
    <p v-if="phase === 'error'" class="mt-3 flex items-center gap-2 rounded-2xl bg-danger-soft p-3 text-sm text-danger" role="alert"><Icon name="alert" :size="16" />{{ error }}</p>

    <div v-if="phase === 'recognizing' || phase === 'done'" class="lg:grid lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)] lg:gap-5">
      <!-- 截图：桌面端固定在左侧；手机端默认折叠成一条缩略栏 -->
      <aside class="lg:sticky lg:top-20 lg:self-start">
        <button
          v-if="phase === 'done'"
          class="mb-3 flex w-full cursor-pointer items-center gap-3 rounded-2xl border border-edge bg-white/60 p-2 text-left lg:hidden"
          :aria-expanded="imgOpen"
          @click="imgOpen = !imgOpen"
        >
          <img :src="previewUrl" alt="" class="h-12 w-12 shrink-0 rounded-xl object-cover object-top" />
          <span class="min-w-0 flex-1 truncate text-[13px] text-ink-2">{{ result?.page || '查看截图' }}</span>
          <Icon name="chevron-down" :size="18" class="mr-1 shrink-0 text-mute transition-transform duration-300" :class="{ 'rotate-180': imgOpen }" />
        </button>
        <div
          class="relative mb-3 overflow-hidden rounded-2xl border border-edge bg-white/60 lg:block"
          :class="phase === 'done' && !imgOpen ? 'hidden' : ''"
        >
          <img :src="previewUrl" alt="上传的截图" class="max-h-[70vh] w-full object-contain" />
          <template v-if="phase === 'recognizing'">
            <div class="absolute inset-0 bg-brand/5" />
            <div class="scan-line absolute inset-x-0 h-24" />
          </template>
        </div>
        <p v-if="phase === 'done' && result?.page" class="mb-3 hidden text-[13px] leading-relaxed text-ink-2 lg:block">
          <Icon name="sparkles" :size="14" class="mr-1 inline text-brand" />{{ result.page }}
        </p>
      </aside>

      <section class="min-w-0">
        <div v-if="phase === 'recognizing'" class="space-y-2.5" aria-busy="true">
          <p class="flex items-center gap-2 text-sm font-medium text-brand"><Icon name="sparkles" :size="16" class="animate-pulse" />AI 正在识别截图里的条目…<AiTag /></p>
          <div v-for="n in 5" :key="n" class="skeleton-bar h-[68px] rounded-2xl" />
        </div>

        <template v-else>
          <!-- 概览 + 筛选 -->
          <div class="flex flex-wrap items-center gap-2">
            <p class="flex flex-wrap items-center gap-x-2 text-[15px] font-semibold">
              识别出 {{ counts.all }} 个条目<AiTag />
              <span v-if="resolving" class="ml-1 inline-flex items-center gap-1 text-[13px] font-normal text-brand"><Icon name="refresh" :size="13" class="animate-spin" />正在对应 GitHub（{{ counts.all - counts.resolving }}/{{ counts.all }}）</span>
            </p>
            <button class="btn-ghost btn-sm ml-auto" @click="reset"><Icon name="refresh" :size="15" />换一张</button>
          </div>
          <div v-if="counts.all > 1" class="scrollbar-none -mx-1 mt-2 flex gap-1.5 overflow-x-auto px-1 pb-1">
            <button
              v-for="f in FILTERS"
              :key="f[0]"
              class="flex h-8 shrink-0 cursor-pointer items-center gap-1 rounded-full px-3 text-[13px] transition-colors duration-300"
              :class="filter === f[0] ? 'bg-brand font-medium text-white' : 'border border-edge bg-white/60 text-ink-2 hover:bg-white'"
              @click="filter = f[0]"
            >{{ f[1] }}<span class="tabular-nums opacity-75">{{ f[2] }}</span></button>
          </div>

          <p v-if="!counts.all" class="panel mt-3 px-5 py-8 text-center text-sm text-ink-2">截图里没有识别到 Skill / 模型 / 仓库</p>

          <p v-if="compareOn && counts.all" class="mt-2 flex items-center gap-1.5 px-1 text-[13px] text-brand">
            <span class="tag bg-brand text-white">AI 智能对比</span>勾选要对比的仓库（已收录的也可以），在底部对比栏开始对比
          </p>
          <div v-else-if="counts.all > 1 && selectable.length" class="mt-2 flex items-center gap-2 px-1 text-[13px] text-ink-2">
            <div class="flex cursor-pointer items-center gap-2" @click="toggleAll">
              <CheckBox :checked="allPicked" label="全选可加入的" @toggle="toggleAll" />全选可加入的（{{ selectable.length }}）
            </div>
          </div>

          <!-- 列表 -->
          <ul class="mt-2 space-y-2">
            <li
              v-for="{ it, i } in visible"
              :key="i"
              v-reveal="i"
              class="panel overflow-hidden transition-[background-color,box-shadow] duration-300"
              :class="(compareOn ? comparable(it) && inCompare(compareEntry(it)) : selected.has(i) && it.state === 'matched') ? 'bg-white/85 ring-2 ring-brand/40' : ''"
            >
              <div
                class="flex gap-3 p-3"
                :class="(compareOn ? comparable(it) : it.state === 'matched') ? 'cursor-pointer' : ''"
                @click="toggle(i)"
              >
                <!-- 勾选 / 状态 -->
                <div class="flex w-7 shrink-0 flex-col items-center gap-1.5 pt-0.5">
                  <CheckBox
                    v-if="compareOn && comparable(it)"
                    tone="compare"
                    :checked="inCompare(compareEntry(it))"
                    :label="`对比 ${it.name}`"
                    @toggle="toggle(i)"
                  />
                  <CheckBox v-else-if="!compareOn && it.state === 'matched'" :checked="selected.has(i)" :label="`选择 ${it.name}`" @toggle="toggle(i)" />
                  <span v-else-if="it.state === 'resolving'" class="text-brand"><Icon name="refresh" :size="16" class="animate-spin" /></span>
                  <span v-else-if="busyTip(it)" class="cursor-help text-brand" :title="busyTip(it)" :aria-label="busyTip(it)" @click.stop="toast(busyTip(it), 'info', 2600)"><Icon name="refresh" :size="16" class="animate-spin" /></span>
                  <span v-else-if="it.state === 'existing'" class="text-ok"><Icon name="check" :size="18" /></span>
                  <span v-else class="text-warn"><Icon name="alert" :size="17" /></span>
                  <span v-if="it.rank" class="text-[11px] font-bold text-mute tabular-nums">#{{ it.rank }}</span>
                </div>

                <div class="min-w-0 flex-1">
                  <div class="flex flex-wrap items-center gap-x-1.5 gap-y-1">
                    <RouterLink
                      v-if="it.state === 'existing' && it.existing_item_id"
                      :to="itemLink(it.existing_item_id)"
                      class="font-semibold break-all text-ink underline decoration-ink/35 underline-offset-4 hover:text-brand hover:decoration-brand"
                      @click.stop
                    >{{ it.name }}</RouterLink>
                    <span v-else class="font-semibold break-all">{{ it.name }}</span>
                    <span class="tag bg-brand-soft text-brand">{{ KIND[it.kind] }}</span>
                    <span v-if="it.stars" class="text-xs text-mute">截图 {{ formatStars(it.stars) }}</span>
                  </div>
                  <p v-if="it.description" class="mt-0.5 line-clamp-2 text-[13px] leading-relaxed text-ink-2">{{ it.description }}</p>

                  <!-- 对应结果 -->
                  <div v-if="it.state === 'resolving'" class="skeleton-bar mt-2 h-7 w-3/4 rounded-lg" />
                  <div v-else-if="it.match" class="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 rounded-xl bg-white/60 px-2.5 py-1.5 text-[12.5px]">
                    <Icon name="github" :size="13" class="text-ink-2" />
                    <a :href="it.match.html_url" target="_blank" rel="noopener" class="min-w-0 cursor-pointer font-medium break-all hover:text-brand" @click.stop>{{ repoLabel(it) }}</a>
                    <span v-if="it.installs" class="text-mute tabular-nums">安装 {{ formatStars(it.installs) }}</span>
                    <span v-else-if="it.match.stars" class="flex items-center gap-0.5 text-mute"><Icon name="star" :size="11" class="fill-amber-400 text-amber-400" />{{ formatStars(it.match.stars) }}</span>
                    <span v-if="it.uncertain" class="tag h-5 bg-warn-soft px-1.5 text-[11px] text-warn">按名称推测，请核对</span>
                    <span v-else class="tag h-5 bg-white/80 px-1.5 text-[11px] text-mute">{{ VIA[it.via] || it.via }}</span>
                  </div>
                  <p v-else class="mt-2 text-[12.5px] text-warn">没找到对应的 GitHub 仓库</p>

                  <!-- 同名提示 -->
                  <div v-if="it.state === 'matched' && sameNameOthers(it).length" class="mt-1.5 flex items-start gap-1.5 rounded-lg bg-warn-soft px-2 py-1.5 text-[12px] leading-relaxed text-warn" @click.stop>
                    <Icon name="alert" :size="13" class="mt-0.5 shrink-0" />
                    <span>
                      库里已有同名条目
                      <template v-for="(x, k) in sameNameOthers(it)" :key="x.id">
                        <span v-if="k">、</span>
                        <RouterLink :to="itemLink(x.id)" class="cursor-pointer font-medium underline">{{ x.repo || x.name }}</RouterLink>
                      </template>
                      ，但来源不同，确认不是同一个再勾选
                    </span>
                  </div>

                  <!-- 操作 -->
                  <div v-if="it.state !== 'resolving'" class="mt-2 flex flex-wrap items-center gap-2 text-[12.5px]" @click.stop>
                    <RouterLink v-if="it.state === 'existing' && it.existing_item_id" :to="itemLink(it.existing_item_id)" class="tag cursor-pointer bg-ok-soft text-ok">已收录 · 查看</RouterLink>
                    <span v-else-if="it.state === 'existing'" class="tag bg-ok-soft text-ok">已收录</span>
                    <span v-else-if="it.state === 'importing'" class="tag bg-brand-soft text-brand">加入中…</span>
                    <button class="cursor-pointer text-brand hover:underline" @click="startSearch(i)">
                      {{ it.state === 'unmatched' ? '手动搜索' : it.state === 'existing' ? '不是同一个？' : '对应错了？换一个' }}
                    </button>
                  </div>

                  <!-- 手动搜索 -->
                  <div v-if="openSearch === i" class="mt-2" @click.stop>
                    <form class="flex gap-2" @submit.prevent="runSearch">
                      <input v-model="searchQ" class="field h-9 sm:h-9" :aria-label="`搜索 ${it.name} 的仓库`" />
                      <button class="btn-glass btn-sm shrink-0"><Icon name="search" :size="15" />搜索</button>
                    </form>
                    <p v-if="searchRes === 'loading'" class="mt-2 text-xs text-mute">搜索中…</p>
                    <ul v-else-if="searchRes?.length" class="mt-2 divide-y divide-line overflow-hidden rounded-xl border border-edge bg-white/70">
                      <li v-for="r in searchRes" :key="r.full_name + (r.skill_id || '')">
                        <button class="flex w-full cursor-pointer items-center gap-2 px-3 py-2 text-left text-[13px] transition-colors duration-200 hover:bg-brand-soft" @click="choose(i, r)">
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

          <!-- v3.3.26 统一的加入栏：只在有勾选时出现 -->
          <JoinBar :show="phase === 'done' && !compareOn" :count="pickedCount" :note="counts.existing ? `${counts.existing} 个已在库中会跳过` : ''" :posting="importing" @join="doImport" />
        </template>
      </section>
    </div>
  </div>
</template>

<style scoped>
.scan-line {
  background: linear-gradient(180deg, transparent, rgb(30 86 214 / 0.28) 70%, rgb(30 86 214 / 0.55) 98%, transparent);
  animation: scan 1.8s cubic-bezier(0.45, 0, 0.55, 1) infinite alternate;
}
@keyframes scan {
  from { top: -6rem; }
  to { top: 100%; }
}
</style>
