<script setup>
import { useItemLink } from '../composables/itemLink'
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { api, formatTime } from '../api'
import AppSelect from './AppSelect.vue'
import Icon from './Icon.vue'

const itemLink = useItemLink()
const route = useRoute()
const router = useRouter()

const view = ref('logs') // logs / tasks
const data = ref(null)
const rows = ref([])
const page = ref(1)
const loading = ref(false)
const f = ref({ source: '', level: '', stage: '', trigger: '', q: '' })
const taskFilter = computed(() => Number(route.query.task) || null)

const LEVEL = {
  success: ['成功', 'bg-ok-soft text-ok', 'check'],
  warn: ['警告', 'bg-warn-soft text-warn', 'alert'],
  error: ['失败', 'bg-danger-soft text-danger', 'x'],
  info: ['记录', 'bg-white/70 text-ink-2', 'inbox'],
}
const LEVELS = [['', '全部'], ['problem', '有问题'], ['success', '成功'], ['warn', '警告'], ['error', '失败']]
const SOURCES = [['', '全部来源'], ['auto', '系统加入'], ['manual', '人工加入']]
const stageOptions = computed(() => [{ value: '', label: '全部环节' }, ...Object.entries(data.value?.stages || {}).map(([k, v]) => ({ value: k, label: v }))])
const triggerOptions = computed(() => [{ value: '', label: '全部途径' }, ...Object.entries(data.value?.triggers || {}).map(([k, v]) => ({ value: k, label: v }))])

async function load(reset = true) {
  if (reset) page.value = 1
  loading.value = true
  try {
    const p = new URLSearchParams({ ...f.value, page: page.value, size: 30 })
    if (taskFilter.value) p.set('task_id', taskFilter.value)
    const d = await api(`/api/logs?${p}`)
    data.value = d
    rows.value = reset ? d.items : [...rows.value, ...d.items]
  } finally {
    loading.value = false
  }
}

let t
watch(() => ({ ...f.value }), () => {
  clearTimeout(t)
  t = setTimeout(() => load(), 250)
})
watch(taskFilter, () => load())

function clearTask() {
  const q = { ...route.query }
  delete q.task
  router.replace({ query: q })
}

// ---- 批次任务 ----
const tasks = ref(null)
const openTask = ref(null)
const taskDetail = ref({})
const TASK_STATUS = {
  running: ['进行中', 'bg-brand-soft text-brand'],
  ok: ['全部成功', 'bg-ok-soft text-ok'],
  partial: ['部分成功', 'bg-warn-soft text-warn'],
  failed: ['失败', 'bg-danger-soft text-danger'],
}
const ITEM_ICON = {
  pending: ['clock', 'text-mute'],
  running: ['refresh', 'animate-spin text-brand'],
  ok: ['check', 'text-ok'],
  failed: ['alert', 'text-danger'],
  deferred: ['clock', 'text-warn'],
}

async function loadTasks() {
  tasks.value = await api('/api/tasks?size=30')
}
async function toggleTask(id) {
  openTask.value = openTask.value === id ? null : id
  if (openTask.value) taskDetail.value = { ...taskDetail.value, [id]: await api(`/api/tasks/${id}`) }
}
function duration(a, b) {
  if (!a || !b) return ''
  const s = Math.round((new Date(b) - new Date(a)) / 1000)
  return s < 60 ? `${s} 秒` : `${Math.floor(s / 60)} 分 ${s % 60} 秒`
}

watch(view, (v) => v === 'tasks' && loadTasks())
onMounted(() => load())
</script>

<template>
  <div>
    <div class="flex flex-wrap items-center gap-2">
      <div class="glass flex rounded-xl p-[3px] text-sm">
        <button
          v-for="v in [['logs', '日志明细'], ['tasks', '批次任务']]"
          :key="v[0]"
          class="h-9 cursor-pointer rounded-[5px] px-4 transition-colors duration-300"
          :class="view === v[0] ? 'bg-brand font-semibold text-white' : 'text-ink-2 hover:text-ink'"
          @click="view = v[0]"
        >{{ v[1] }}</button>
      </div>
      <p class="text-[13px] text-mute">记录每个条目加入平台时每个环节的结果：成功、警告、失败，以及原因。</p>
    </div>

    <!-- ================= 日志明细 ================= -->
    <template v-if="view === 'logs'">
      <div v-if="data" class="mt-4 grid grid-cols-3 gap-2.5">
        <div v-for="k in ['success', 'warn', 'error']" :key="k" class="glass rounded-2xl px-4 py-3">
          <p class="text-xs text-mute">近 7 天{{ LEVEL[k][0] }}</p>
          <p class="mt-0.5 text-xl font-bold tabular-nums" :class="LEVEL[k][1].split(' ')[1]">{{ data.counts_7d[k] }}</p>
        </div>
      </div>

      <!-- 筛选 -->
      <div class="mt-4 space-y-2.5">
        <div class="flex flex-wrap gap-2">
          <div class="glass flex rounded-xl p-[3px] text-[13px]">
            <button
              v-for="s in SOURCES"
              :key="s[0]"
              class="h-8 cursor-pointer rounded-[5px] px-3 transition-colors duration-300"
              :class="f.source === s[0] ? 'bg-white font-semibold text-ink shadow-sm' : 'text-ink-2'"
              @click="f.source = s[0]"
            >{{ s[1] }}</button>
          </div>
          <div class="scrollbar-none flex gap-1.5 overflow-x-auto">
            <button
              v-for="l in LEVELS"
              :key="l[0]"
              class="h-9 shrink-0 cursor-pointer rounded-full px-3.5 text-[13px] transition-colors duration-300"
              :class="f.level === l[0] ? 'bg-brand text-white' : 'border border-edge bg-white/60 text-ink-2 hover:bg-white'"
              @click="f.level = l[0]"
            >{{ l[1] }}</button>
          </div>
        </div>
        <div class="grid gap-2 sm:grid-cols-[1fr_1fr_2fr]">
          <AppSelect v-model="f.stage" :options="stageOptions" label="环节" />
          <AppSelect v-model="f.trigger" :options="triggerOptions" label="途径" />
          <input v-model="f.q" type="search" class="field h-10" placeholder="搜索条目名、仓库或原因" aria-label="搜索日志" />
        </div>
        <p v-if="taskFilter" class="flex items-center gap-2 rounded-xl bg-brand-soft px-3 py-2 text-[13px] text-brand">
          <Icon name="layers" :size="14" />只看批次任务 #{{ taskFilter }} 的日志
          <button class="ml-auto cursor-pointer underline" @click="clearTask">看全部</button>
        </p>
      </div>

      <!-- 列表 -->
      <p class="mt-4 text-[13px] text-mute">共 {{ data?.total ?? 0 }} 条</p>
      <ul class="mt-2 space-y-2">
        <li v-for="r in rows" :key="r.id" class="panel flex gap-3 p-3.5">
          <span class="grid h-8 w-8 shrink-0 place-items-center rounded-xl" :class="LEVEL[r.level][1]"><Icon :name="LEVEL[r.level][2]" :size="16" /></span>
          <div class="min-w-0 flex-1">
            <div class="flex flex-wrap items-center gap-x-2 gap-y-1">
              <RouterLink v-if="r.item_id" :to="itemLink(r.item_id)" class="cursor-pointer font-semibold underline decoration-ink/35 underline-offset-4 hover:text-brand hover:decoration-brand">{{ r.item_name || '（未命名）' }}</RouterLink>
              <span v-else class="font-semibold">{{ r.item_name || r.repo || '—' }}</span>
              <span class="tag" :class="r.source === 'auto' ? 'bg-ok-soft text-ok' : 'bg-brand-soft text-brand'">{{ r.source === 'auto' ? '系统' : '人工' }}</span>
              <span class="tag bg-white/70 text-ink-2">{{ r.trigger_label }}</span>
              <span class="tag border border-edge bg-white/50 text-ink-2">环节：{{ r.stage_label }}</span>
            </div>
            <p class="mt-1 text-[13.5px] leading-relaxed break-words" :class="r.level === 'error' ? 'text-danger' : r.level === 'warn' ? 'text-warn' : 'text-ink-2'">{{ r.message }}</p>
            <p class="mt-1 flex flex-wrap gap-x-3 text-xs text-mute">
              <time :datetime="r.created_at">{{ formatTime(r.created_at) }}</time>
              <span v-if="r.repo" class="break-all">{{ r.repo }}</span>
              <span v-if="r.duration_ms != null">耗时 {{ (r.duration_ms / 1000).toFixed(1) }} 秒</span>
              <RouterLink v-if="r.task_id && !taskFilter" :to="{ query: { ...route.query, task: r.task_id } }" class="cursor-pointer text-brand hover:underline">批次 #{{ r.task_id }}</RouterLink>
            </p>
          </div>
        </li>
        <li v-if="data && !rows.length" class="panel px-6 py-10 text-center text-sm text-mute">没有符合条件的日志</li>
      </ul>
      <div class="mt-4 flex justify-center">
        <button v-if="data && rows.length < data.total" class="btn-glass w-full sm:w-auto" :disabled="loading" @click="page++; load(false)">
          {{ loading ? '加载中…' : '加载更多' }}
        </button>
      </div>
    </template>

    <!-- ================= 批次任务 ================= -->
    <template v-else>
      <div v-if="!tasks" class="mt-4 space-y-2.5"><div v-for="n in 3" :key="n" class="skeleton-bar h-20 rounded-[12px]" /></div>
      <ul v-else class="mt-4 space-y-2.5">
        <li v-for="t in tasks.items" :key="t.id" class="panel p-4">
          <button class="flex w-full cursor-pointer flex-wrap items-center gap-x-2.5 gap-y-1 text-left" :aria-expanded="openTask === t.id" @click="toggleTask(t.id)">
            <span class="tag" :class="TASK_STATUS[t.status]?.[1]">{{ TASK_STATUS[t.status]?.[0] }}</span>
            <span class="tag" :class="t.source === 'auto' ? 'bg-ok-soft text-ok' : 'bg-brand-soft text-brand'">{{ t.source === 'auto' ? '系统' : '人工' }}</span>
            <span class="min-w-0 flex-1 truncate font-medium">{{ t.title }}</span>
            <span class="text-xs text-mute tabular-nums">成功 {{ t.done - t.failed }} · 失败 {{ t.failed }} · 共 {{ t.total }}</span>
            <Icon name="chevron-down" :size="16" class="text-mute transition-transform duration-300" :class="{ 'rotate-180': openTask === t.id }" />
          </button>
          <div class="mt-2.5 h-1.5 overflow-hidden rounded-full bg-ink/10">
            <div class="h-full rounded-full bg-linear-90 from-brand to-brand-2 transition-[width] duration-700" :style="{ width: (t.total ? (t.done / t.total) * 100 : 100) + '%' }" />
          </div>
          <p class="mt-1.5 text-xs text-mute">
            {{ formatTime(t.created_at) }}<template v-if="t.finished_at"> · 用时 {{ duration(t.created_at, t.finished_at) }}</template>
          </p>
          <div v-if="openTask === t.id && taskDetail[t.id]" class="mt-3 border-t border-line pt-3">
            <ol class="space-y-1.5">
              <li v-for="i in taskDetail[t.id].items" :key="i.seq" class="flex items-start gap-2 text-[13px]">
                <Icon :name="ITEM_ICON[i.status]?.[0]" :size="15" class="mt-0.5 shrink-0" :class="ITEM_ICON[i.status]?.[1]" />
                <span class="w-6 shrink-0 text-right text-mute tabular-nums">{{ i.seq }}</span>
                <div class="min-w-0 flex-1">
                  <RouterLink v-if="i.item_id" :to="itemLink(i.item_id)" class="cursor-pointer font-medium underline decoration-ink/35 underline-offset-4 hover:text-brand hover:decoration-brand">{{ i.name }}</RouterLink>
                  <span v-else class="font-medium">{{ i.name }}</span>
                  <span v-if="i.status === 'running'" class="ml-1 text-brand">· {{ i.stage_label }}</span>
                  <span v-else-if="i.status === 'failed'" class="ml-1 text-danger">· 失败于「{{ i.stage_label }}」</span>
                  <p v-if="i.message" class="break-words text-xs" :class="i.status === 'failed' ? 'text-danger' : 'text-mute'">{{ i.message }}</p>
                </div>
              </li>
            </ol>
            <RouterLink :to="{ query: { tab: 'logs', task: t.id } }" class="mt-3 inline-flex cursor-pointer items-center gap-1 text-[13px] text-brand hover:underline" @click="view = 'logs'">
              查看这批的详细日志<Icon name="chevron-right" :size="14" />
            </RouterLink>
          </div>
        </li>
        <li v-if="!tasks.items.length" class="panel px-6 py-10 text-center text-sm text-mute">还没有批次任务</li>
      </ul>
    </template>
  </div>
</template>
