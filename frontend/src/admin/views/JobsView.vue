<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api, formatTime, isCancelled } from '../../api'
import Icon from '../../components/Icon.vue'
import { confirmDialog } from '../../composables/dialog'
import { toast } from '../../composables/toast'

// 采集任务：每日自动采集的运行记录（星标快照 → 榜单 → 发现新仓库 → AI 提炼），可以手动运行一次，以及几个批量维护操作
const data = ref(null)
const expanded = ref(null)
let timer

const STATUS = {
  running: ['运行中', 'tag-blue'],
  ok: ['完成', 'tag-ok'],
  partial: ['额度用完 · 明天继续', 'tag-warn'],
  warning: ['部分阶段出错', 'tag-warn'],
  failed: ['失败', 'tag-bad'],
}
const STAGES = [
  ['snapshot', '星标快照'],
  ['rankings', '生成榜单'],
  ['discover', '发现新仓库'],
  ['extract', 'AI 提炼'],
]
const TRIGGER = { schedule: '定时', manual: '手动' }
const running = computed(() => data.value?.running)
// v3.1 图片集覆盖率（已发布条目里有多张图的数量）
const coverage = ref(null)
async function loadCoverage() {
  try {
    coverage.value = await api('/api/admin/gallery-coverage', { admin: true })
  } catch {}
}

async function load() {
  clearTimeout(timer)
  try {
    data.value = await api('/api/jobs')
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  }
  if (data.value?.running) timer = setTimeout(load, 3000) // 运行中每 3 秒刷新进度
}

async function call(path, body, done) {
  try {
    const r = await api(path, { method: 'POST', admin: true, body })
    toast(done(r), 'success')
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  }
}

async function trigger() {
  if (!(await confirmDialog({ title: '立即运行一次采集？', message: '会按顺序做星标快照、生成榜单、发现新仓库和 AI 提炼，可能需要较长时间。', okText: '开始采集' }))) return
  await call('/api/jobs/crawl', undefined, () => '已开始采集')
  setTimeout(load, 600)
}
async function reclassify() {
  if (!(await confirmDialog({ title: '让 AI 重新判定全部条目的分类？', message: '重新判定领域分类和使用类型，不会重写介绍；人工锁定过的分类会保留。', okText: '开始重新分类' }))) return
  call('/api/reclassify', { only_missing: false }, (r) => (r.queued ? '已开始重新分类' : '没有需要处理的条目'))
}
const fillBlurbs = () => call('/api/rankings/blurbs', { force: false }, (r) => (r.queued ? '正在为在榜条目生成中文详解' : '在榜条目都已有详解'))
const fillCovers = () => call('/api/items/covers-missing', undefined, (r) => (r.queued ? `正在为 ${r.queued} 个条目生成封面` : '所有条目都已有封面'))
async function redrawCovers() {
  if (!(await confirmDialog({ title: '重画全部 AI 封面？', message: '按当前提示词把所有 AI 画的封面重画一遍（README 截图不动），画失败的保留旧图。几百张大约要半小时到一小时，进度在右下角。', okText: '开始重画' }))) return
  await call('/api/items/covers-redraw', undefined, (r) => (r.task_id ? '已开始重画 AI 封面' : '没有 AI 封面需要重画'))
}
async function fillGallery() {
  if (!(await confirmDialog({ title: '给所有条目补图片集？', message: '从每个条目的 GitHub 文档里抓最多 5 张截图做成图片集（已有多张图、或人工改过图片的跳过）。几百个条目大约要几十分钟，进度在右下角。建议避开凌晨采集时段。', okText: '开始' }))) return
  call('/api/admin/items/images-backfill', undefined, (r) => (r.queued ? `已开始：${r.queued} 个条目，进度在右下角` : '没有需要补图的条目'))
}

function duration(r) {
  if (!r.finished_at) return ''
  const s = Math.round((new Date(r.finished_at) - new Date(r.started_at)) / 1000)
  return s < 60 ? `${s} 秒` : `${Math.floor(s / 60)} 分 ${s % 60} 秒`
}
function summary(st) {
  const parts = []
  if (st.snapshots != null) parts.push(`快照 ${st.snapshots}/${st.snapshot_total ?? st.snapshots}`)
  if (st.daily_boards != null) parts.push(`日榜 ${st.daily_boards} 个分类`)
  if (st.weekly_boards != null) parts.push(`周榜 ${st.weekly_boards} 个分类`)
  if (st.candidates != null) parts.push(`候选 ${st.candidates}`)
  if (st.new_items) parts.push(`新增 ${st.new_items}`)
  if (st.pending_review) parts.push(`待确认 ${st.pending_review}`)
  if (st.ignored) parts.push(`不相关 ${st.ignored}`)
  if (st.extracted) parts.push(`提炼 ${st.extracted}`)
  return parts.join(' · ')
}
function stageState(r, key) {
  const order = STAGES.map((s) => s[0])
  if (r.stats.stage_seconds?.[key] != null) return r.status === 'partial' && order.indexOf(key) === order.indexOf(Object.keys(r.stats.stage_seconds).pop()) ? 'stopped' : 'done'
  if (r.stats.stage === key && r.status === 'running') return 'active'
  if (r.stats.stage_errors?.[key]) return 'stopped'
  return 'todo'
}
const rateText = (rate) => Object.entries(rate || {}).map(([k, v]) => `${k} ${v.remaining}/${v.limit}`).join('　')

onMounted(() => {
  load()
  loadCoverage()
})
onBeforeUnmount(() => clearTimeout(timer))
</script>

<template>
  <div>
    <div class="flex flex-wrap items-end gap-3">
      <div>
        <h1 class="m-0 text-xl font-semibold">采集任务</h1>
        <p class="mt-1 mb-0 text-[13px] text-mute">顺序：星标快照 → 生成榜单 → 榜单中文详解 → 发现新仓库（AI 判断是否收录）→ AI 提炼。额度用完会等下一小时重置，窗口结束前没做完的明天继续。</p>
      </div>
      <button class="btn btn-primary ml-auto" :disabled="running" @click="trigger">
        <Icon :name="running ? 'refresh' : 'play'" :size="15" :class="{ 'animate-spin': running }" />{{ running ? '采集中…' : '立即运行一次' }}
      </button>
    </div>

    <div v-if="!data" class="skeleton mt-5 h-64" />
    <template v-else>
      <div class="mt-5 grid grid-cols-2 gap-3.5 xl:grid-cols-4">
        <div class="card px-[18px] py-3.5"><p class="m-0 text-[13px] text-mute">工作窗口</p><b class="mt-1 block text-[17px]">{{ data.window.start }} – {{ data.window.end }}</b></div>
        <div class="card px-[18px] py-3.5"><p class="m-0 text-[13px] text-mute">下次运行</p><b class="mt-1 block text-[17px]">{{ data.enabled ? (data.next_run ? formatTime(data.next_run) : '—') : '已关闭' }}</b></div>
        <div class="card px-[18px] py-3.5"><p class="m-0 text-[13px] text-mute">GitHub Token</p><b class="mt-1 block text-[17px]" :class="data.github_token ? 'text-ok' : 'text-warn'">{{ data.github_token ? '已配置 · 5000 次/小时' : '未配置 · 60 次/小时' }}</b></div>
        <div class="card px-[18px] py-3.5"><p class="m-0 text-[13px] text-mute">待处理</p><b class="mt-1 block text-[17px]">待确认 {{ data.pending_review }} · 待提炼 {{ data.pending_extract }}</b></div>
      </div>

      <section class="card mt-3.5">
        <div class="card-hd"><h2>批量维护</h2><span v-if="data.rate && Object.keys(data.rate).length" class="ml-auto text-xs text-mute">当前额度：{{ rateText(data.rate) }}</span></div>
        <div class="card-bd flex flex-wrap gap-2">
          <button class="btn" @click="reclassify"><Icon name="layers" :size="15" />AI 重新分类</button>
          <button class="btn" @click="fillBlurbs"><Icon name="file-text" :size="15" />补齐榜单详解</button>
          <button class="btn" @click="fillCovers"><Icon name="image" :size="15" />补全 AI 封面</button>
          <button class="btn" @click="redrawCovers"><Icon name="refresh" :size="15" />重画全部 AI 封面</button>
          <button class="btn" @click="fillGallery"><Icon name="image" :size="15" />批量补图片集<span v-if="coverage" class="ml-1 font-mono text-[11.5px] text-mute">已覆盖 {{ coverage.with_gallery }} / {{ coverage.total }}</span></button>
        </div>
      </section>

      <section class="card mt-3.5">
        <div class="card-hd"><h2>运行记录</h2></div>
        <p v-if="!data.runs.length" class="empty">还没有运行记录</p>
        <ul class="m-0 list-none p-0">
          <li v-for="r in data.runs" :key="r.id" class="border-b border-line px-[18px] py-3.5 last:border-0">
            <button class="flex w-full flex-wrap items-center gap-x-3 gap-y-1 text-left" :aria-expanded="expanded === r.id" @click="expanded = expanded === r.id ? null : r.id">
              <span class="tag" :class="STATUS[r.status]?.[1] || 'tag-gray'">{{ STATUS[r.status]?.[0] || r.status }}</span>
              <span class="font-medium tabular-nums">{{ formatTime(r.started_at) }}</span>
              <span class="text-xs text-mute">{{ TRIGGER[r.stats.trigger] || '' }}<template v-if="duration(r)"> · 用时 {{ duration(r) }}</template></span>
              <Icon name="chevron-down" :size="15" class="ml-auto text-mute transition-transform" :class="{ 'rotate-180': expanded === r.id }" />
            </button>
            <div class="mt-2.5 grid grid-cols-4 gap-1.5">
              <div v-for="s in STAGES" :key="s[0]" class="min-w-0">
                <div class="h-1.5 rounded-full" :class="{ 'bg-primary': stageState(r, s[0]) === 'done', 'animate-pulse bg-primary/50': stageState(r, s[0]) === 'active', 'bg-warn/60': stageState(r, s[0]) === 'stopped', 'bg-[#e9edf3]': stageState(r, s[0]) === 'todo' }" />
                <p class="mt-1 mb-0 truncate text-[11px] text-mute">{{ s[1] }}<template v-if="r.stats.stage_seconds?.[s[0]] != null"> {{ r.stats.stage_seconds[s[0]] }}s</template></p>
              </div>
            </div>
            <p v-if="summary(r.stats)" class="mt-2 mb-0 text-[13px] text-ink-2">{{ summary(r.stats) }}</p>
            <div v-if="expanded === r.id" class="mt-3 space-y-2 border-t border-line pt-3 text-xs">
              <p v-if="r.error" class="m-0 rounded-md bg-bad-soft p-2.5 whitespace-pre-wrap text-bad">{{ r.error }}</p>
              <div v-if="r.stats.stage_errors">
                <p class="m-0 font-medium text-ink-2">阶段错误</p>
                <ul class="mt-1 list-disc pl-4 text-mute"><li v-for="(msg, k) in r.stats.stage_errors" :key="k" class="break-all">{{ STAGES.find((x) => x[0] === k)?.[1] || k }}：{{ msg }}</li></ul>
              </div>
              <div v-for="k in ['snapshot_errors', 'discover_errors']" :key="k">
                <template v-if="r.stats[k]?.length">
                  <p class="m-0 font-medium text-ink-2">{{ k === 'snapshot_errors' ? '快照错误' : '发现阶段错误' }}（{{ r.stats[k].length }}）</p>
                  <ul class="mt-1 list-disc pl-4 text-mute"><li v-for="(e, i) in r.stats[k].slice(0, 10)" :key="i" class="break-all">{{ e }}</li></ul>
                </template>
              </div>
              <p v-if="r.stats.rate" class="m-0 text-mute">结束时额度：{{ rateText(r.stats.rate) }}</p>
              <p v-if="r.stats.skipped_over_limit" class="m-0 text-mute">超出单次上限、留到下次的候选：{{ r.stats.skipped_over_limit }}</p>
            </div>
          </li>
        </ul>
      </section>
    </template>
  </div>
</template>
