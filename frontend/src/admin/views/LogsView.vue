<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, formatTime, isCancelled } from '../../api'
import Icon from '../../components/Icon.vue'
import { toast } from '../../composables/toast'
import ASelect from '../components/ASelect.vue'

// 入库日志：每个条目加入平台时每个环节的结果（成功 / 警告 / 失败及原因），以及批次任务的进度
const route = useRoute()
const router = useRouter()
const view = computed(() => (route.query.view === 'tasks' ? 'tasks' : 'logs'))
const setView = (v) => router.replace({ query: { ...route.query, view: v === 'tasks' ? 'tasks' : undefined } })

const data = ref(null)
const rows = ref([])
const page = ref(1)
const f = ref({ source: '', level: '', stage: '', trigger: '', q: '' })
const taskFilter = computed(() => Number(route.query.task) || null)

const LEVEL = {
  success: ['成功', 'tag-ok', 'check'],
  warn: ['警告', 'tag-warn', 'alert'],
  error: ['失败', 'tag-bad', 'x'],
  info: ['记录', 'tag-gray', 'inbox'],
}
const sourceOptions = [{ value: '', label: '全部来源' }, { value: 'auto', label: '系统加入' }, { value: 'manual', label: '人工加入' }]
const levelOptions = [{ value: '', label: '全部结果' }, { value: 'problem', label: '有问题（警告 + 失败）' }, { value: 'success', label: '成功' }, { value: 'warn', label: '警告' }, { value: 'error', label: '失败' }]
const stageOptions = computed(() => [{ value: '', label: '全部环节' }, ...Object.entries(data.value?.stages || {}).map(([k, v]) => ({ value: k, label: v }))])
const triggerOptions = computed(() => [{ value: '', label: '全部途径' }, ...Object.entries(data.value?.triggers || {}).map(([k, v]) => ({ value: k, label: v }))])

function fail(e) {
  if (!isCancelled(e)) toast(e.message, 'error')
}

async function load(more = false) {
  page.value = more ? page.value + 1 : 1
  const p = new URLSearchParams({ ...f.value, page: page.value, size: 30 })
  if (taskFilter.value) p.set('task_id', taskFilter.value)
  try {
    const d = await api(`/api/logs?${p}`)
    data.value = d
    rows.value = more ? [...rows.value, ...d.items] : d.items
  } catch (e) {
    fail(e)
  }
}

function showTask(id) {
  router.replace({ query: { ...route.query, view: undefined, task: id } })
}
function clearTask() {
  const { task, ...rest } = route.query
  router.replace({ query: rest })
}

// ---- 批次任务 ----
const tasks = ref(null)
const openTask = ref(null)
const taskDetail = ref({})
const TASK_STATUS = { running: ['进行中', 'tag-blue'], ok: ['全部成功', 'tag-ok'], partial: ['部分成功', 'tag-warn'], failed: ['失败', 'tag-bad'] }
const ITEM_ICON = { pending: ['clock', 'text-mute'], running: ['refresh', 'animate-spin text-primary'], ok: ['check', 'text-ok'], failed: ['alert', 'text-bad'], deferred: ['clock', 'text-warn'] }

async function loadTasks() {
  try {
    tasks.value = await api('/api/tasks?size=30')
  } catch (e) {
    fail(e)
  }
}
async function toggleTask(id) {
  openTask.value = openTask.value === id ? null : id
  if (openTask.value) {
    try {
      taskDetail.value = { ...taskDetail.value, [id]: await api(`/api/tasks/${id}`) }
    } catch (e) {
      fail(e)
    }
  }
}
function duration(a, b) {
  if (!a || !b) return ''
  const s = Math.round((new Date(b) - new Date(a)) / 1000)
  return s < 60 ? `${s} 秒` : `${Math.floor(s / 60)} 分 ${s % 60} 秒`
}

let t
watch(f, () => {
  clearTimeout(t)
  t = setTimeout(() => load(), 250)
}, { deep: true })
watch(taskFilter, () => load())
watch(view, (v) => (v === 'tasks' ? !tasks.value && loadTasks() : !data.value && load()), { immediate: true })
onMounted(() => {})
</script>

<template>
  <div>
    <div class="flex flex-wrap items-end gap-3">
      <div>
        <h1 class="m-0 text-xl font-semibold">入库日志</h1>
        <p class="mt-1 mb-0 text-[13px] text-mute">每个条目加入平台时每个环节的结果：成功、警告、失败，以及原因。</p>
      </div>
      <div class="seg ml-auto">
        <button :class="{ on: view === 'logs' }" @click="setView('logs')">日志明细</button>
        <button :class="{ on: view === 'tasks' }" @click="setView('tasks')">批次任务</button>
      </div>
    </div>

    <template v-if="view === 'logs'">
      <div v-if="data" class="mt-5 grid grid-cols-3 gap-3.5">
        <div v-for="k in ['success', 'warn', 'error']" :key="k" class="card px-[18px] py-3.5">
          <p class="m-0 text-[13px] text-mute">近 7 天{{ LEVEL[k][0] }}</p>
          <b class="mt-1 block text-2xl tabular-nums" :class="{ 'text-ok': k === 'success', 'text-warn': k === 'warn', 'text-bad': k === 'error' }">{{ data.counts_7d[k] }}</b>
        </div>
      </div>

      <section class="card mt-3.5">
        <div class="grid gap-2.5 border-b border-line p-3.5 sm:grid-cols-2 lg:grid-cols-[140px_180px_160px_160px_1fr]">
          <ASelect v-model="f.source" :options="sourceOptions" label="来源" />
          <ASelect v-model="f.level" :options="levelOptions" label="结果" />
          <ASelect v-model="f.stage" :options="stageOptions" label="环节" />
          <ASelect v-model="f.trigger" :options="triggerOptions" label="途径" />
          <input v-model="f.q" type="search" class="input" placeholder="搜索条目名、仓库或原因" aria-label="搜索日志" />
        </div>
        <p v-if="taskFilter" class="m-0 flex items-center gap-2 border-b border-line bg-primary-soft px-[18px] py-2 text-[13px] text-primary">
          <Icon name="layers" :size="14" />只看批次任务 #{{ taskFilter }} 的日志
          <button class="ml-auto underline" @click="clearTask">看全部</button>
        </p>
        <div v-if="!data" class="card-bd"><div class="skeleton h-60" /></div>
        <p v-else-if="!rows.length" class="empty">没有符合条件的日志</p>
        <ul v-else class="m-0 list-none p-0">
          <li v-for="r in rows" :key="r.id" class="flex gap-3 border-b border-line px-[18px] py-3 last:border-0">
            <span class="tag mt-0.5 h-7 w-7 shrink-0 justify-center p-0" :class="LEVEL[r.level][1]" :title="LEVEL[r.level][0]"><Icon :name="LEVEL[r.level][2]" :size="14" /></span>
            <div class="min-w-0 flex-1">
              <div class="flex flex-wrap items-center gap-x-2 gap-y-1">
                <a v-if="r.item_id" :href="`/items/${r.item_id}`" target="_blank" class="font-semibold hover:text-primary">{{ r.item_name || '（未命名）' }}</a>
                <span v-else class="font-semibold">{{ r.item_name || r.repo || '—' }}</span>
                <span class="tag" :class="r.source === 'auto' ? 'tag-ok' : 'tag-blue'">{{ r.source === 'auto' ? '系统' : '人工' }}</span>
                <span class="tag tag-gray">{{ r.trigger_label }}</span>
                <span class="tag tag-gray">环节：{{ r.stage_label }}</span>
              </div>
              <p class="mt-1 mb-0 text-[13px] break-words" :class="r.level === 'error' ? 'text-bad' : r.level === 'warn' ? 'text-warn' : 'text-ink-2'">{{ r.message }}</p>
              <p class="mt-1 mb-0 flex flex-wrap gap-x-3 text-xs text-mute">
                <time class="tabular-nums">{{ formatTime(r.created_at) }}</time>
                <span v-if="r.repo" class="break-all">{{ r.repo }}</span>
                <span v-if="r.duration_ms != null">耗时 {{ (r.duration_ms / 1000).toFixed(1) }} 秒</span>
                <button v-if="r.task_id && !taskFilter" class="text-primary hover:underline" @click="showTask(r.task_id)">批次 #{{ r.task_id }}</button>
              </p>
            </div>
          </li>
        </ul>
        <div v-if="data" class="flex items-center border-t border-line px-[18px] py-3 text-xs text-mute">
          共 {{ data.total }} 条
          <button v-if="rows.length < data.total" class="btn btn-sm ml-auto" @click="load(true)">加载更多</button>
        </div>
      </section>
    </template>

    <section v-else class="card mt-5">
      <div class="card-hd"><h2>批次任务</h2><span class="text-xs text-mute">导入、截图识别、批量中文化、补封面、每晚采集</span></div>
      <div v-if="!tasks" class="card-bd"><div class="skeleton h-40" /></div>
      <p v-else-if="!tasks.items.length" class="empty">还没有批次任务</p>
      <ul v-else class="m-0 list-none p-0">
        <li v-for="tk in tasks.items" :key="tk.id" class="border-b border-line px-[18px] py-3.5 last:border-0">
          <button class="flex w-full flex-wrap items-center gap-x-2.5 gap-y-1 text-left" :aria-expanded="openTask === tk.id" @click="toggleTask(tk.id)">
            <span class="tag" :class="TASK_STATUS[tk.status]?.[1] || 'tag-gray'">{{ TASK_STATUS[tk.status]?.[0] || tk.status }}</span>
            <span class="tag" :class="tk.source === 'auto' ? 'tag-ok' : 'tag-blue'">{{ tk.source === 'auto' ? '系统' : '人工' }}</span>
            <span class="min-w-0 flex-1 truncate font-medium">{{ tk.title }}</span>
            <span class="text-xs text-mute tabular-nums">成功 {{ tk.done - tk.failed }} · 失败 {{ tk.failed }} · 共 {{ tk.total }}</span>
            <Icon name="chevron-down" :size="15" class="text-mute transition-transform" :class="{ 'rotate-180': openTask === tk.id }" />
          </button>
          <div class="mt-2 h-1.5 overflow-hidden rounded-full bg-[#e9edf3]">
            <div class="h-full rounded-full bg-primary transition-[width] duration-700" :style="{ width: (tk.total ? (tk.done / tk.total) * 100 : 100) + '%' }" />
          </div>
          <p class="mt-1.5 mb-0 text-xs text-mute">{{ formatTime(tk.created_at) }}<template v-if="tk.finished_at"> · 用时 {{ duration(tk.created_at, tk.finished_at) }}</template></p>
          <div v-if="openTask === tk.id && taskDetail[tk.id]" class="mt-3 border-t border-line pt-3">
            <ol class="m-0 list-none space-y-1.5 p-0">
              <li v-for="i in taskDetail[tk.id].items" :key="i.seq" class="flex items-start gap-2 text-[13px]">
                <Icon :name="ITEM_ICON[i.status]?.[0]" :size="15" class="mt-0.5 shrink-0" :class="ITEM_ICON[i.status]?.[1]" />
                <span class="w-6 shrink-0 text-right text-mute tabular-nums">{{ i.seq }}</span>
                <div class="min-w-0 flex-1">
                  <a v-if="i.item_id" :href="`/items/${i.item_id}`" target="_blank" class="font-medium hover:text-primary">{{ i.name }}</a>
                  <span v-else class="font-medium">{{ i.name }}</span>
                  <span v-if="i.status === 'running'" class="ml-1 text-primary">· {{ i.stage_label }}</span>
                  <span v-else-if="i.status === 'failed'" class="ml-1 text-bad">· 失败于「{{ i.stage_label }}」</span>
                  <p v-if="i.message" class="m-0 text-xs break-words" :class="i.status === 'failed' ? 'text-bad' : 'text-mute'">{{ i.message }}</p>
                </div>
              </li>
            </ol>
            <button class="mt-3 inline-flex items-center gap-1 text-[13px] text-primary hover:underline" @click="showTask(tk.id)">查看这批的详细日志<Icon name="chevron-right" :size="14" /></button>
          </div>
        </li>
      </ul>
    </section>
  </div>
</template>
