<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { api, formatTime, isCancelled } from '../../api'
import { toast } from '../../composables/toast'
import { onActionError } from '../composables/handled'
import { askReason } from '../composables/reason'
import { can } from '../composables/usePermissions'
import ATable from './ATable.vue'

// 封面缩略图 / 动图队列：已生成、排队中、缺失、没有动画；缺失的可以重新排队，单个条目也能重新生成。
// 缩略图和动图不入库，状态按文件判断：缺失 = 没有文件也不在队列里（还没生成或生成失败，分不出来）
const stat = ref(null)
const kind = ref('thumb')
const status = ref('missing')
const list = ref(null)
const page = ref(1)
const busy = ref('')
const canWrite = computed(() => can('content', 'w'))
const KINDS = [['thumb', '缩略图'], ['anim', '动图']]
const STATUS_TAG = { done: 'tag-ok', queued: 'tag-blue', missing: 'tag-warn', no_anim: 'tag-gray' }
const mb = (n) => (n == null ? '未知' : `${(n / 1048576).toFixed(1)} MB`)

async function loadStat() {
  try {
    stat.value = await api('/api/admin/cover-queue')
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  }
}
async function loadList(more = false) {
  page.value = more ? page.value + 1 : 1
  try {
    const d = await api(`/api/admin/cover-queue/items?kind=${kind.value}&status=${status.value}&page=${page.value}&page_size=30`)
    list.value = more ? { ...d, items: [...list.value.items, ...d.items] } : d
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  }
}
const statusTabs = computed(() => (kind.value === 'anim' ? ['missing', 'queued', 'no_anim', 'done'] : ['missing', 'queued', 'done']).map((k) => [k, stat.value?.statuses?.[k] || k]))
watch(kind, () => {
  if (kind.value === 'thumb' && status.value === 'no_anim') status.value = 'missing'
  list.value = null
  loadList()
})
watch(status, () => {
  list.value = null
  loadList()
})
loadStat()
loadList()
// 队列有内容时每 8 秒刷新一次
const timer = setInterval(() => {
  if (!document.hidden && stat.value?.queue_length) {
    loadStat()
    if (page.value === 1) loadList()
  }
}, 8000)
onBeforeUnmount(() => clearInterval(timer))

const columns = [
  { key: 'item', label: '条目', mobile: 'title' },
  { key: 'status', label: '状态', mobile: 'meta' },
  { key: 'updated_at', label: '文件时间', align: 'right', hideBelow: 'md', mobile: 'hide' },
  { key: 'actions', label: '', align: 'right', mobile: 'action' },
]
const TEMPLATES = ['封面缺失，重新生成', '封面样式更新后重建']
async function retryAll(includeNoAnim = false) {
  const reason = await askReason({
    title: includeNoAnim ? '重试缺失项（含「没有动画」）' : '重试缺失项',
    impact: includeNoAnim ? '缺失的重新排队，「没有动画」的会清掉标记再尝试一次' : '把缺失的缩略图和动图重新排队',
    templates: TEMPLATES,
    okText: '重新排队',
  })
  if (reason === null) return
  busy.value = 'all'
  try {
    const r = await api('/api/admin/cover-queue/retry-failed', { method: 'POST', body: { kind: 'all', reason, include_no_anim: includeNoAnim } })
    toast(`已排队 ${r.queued} 个，队列共 ${r.queue_length} 个`, 'success')
    await Promise.all([loadStat(), loadList()])
  } catch (e) {
    await onActionError(e)
  } finally {
    busy.value = ''
  }
}
async function regen(row) {
  const reason = await askReason({ title: `重新生成「${row.item.name}」的${kind.value === 'anim' ? '动图' : '缩略图'}`, impact: '会删掉现有文件，并插到队首重新生成', templates: TEMPLATES, okText: '重新生成' })
  if (reason === null) return
  busy.value = String(row.item.id)
  try {
    const r = await api(`/api/admin/items/${row.item.id}/regenerate-cover`, { method: 'POST', body: { kind: kind.value, reason } })
    toast(`已排队，队列共 ${r.queue_length} 个`, 'success')
    await Promise.all([loadStat(), loadList()])
  } catch (e) {
    await onActionError(e)
  } finally {
    busy.value = ''
  }
}
</script>

<template>
  <div>
    <div v-if="!stat" class="mt-5"><div class="skeleton h-28" /></div>
    <template v-else>
      <ul class="m-0 mt-5 grid list-none grid-cols-2 gap-3.5 p-0 lg:grid-cols-4">
        <li class="card px-[18px] py-3.5"><p class="m-0 text-[13px] text-mute">缩略图</p><b class="mt-1 block text-2xl tabular-nums">{{ stat.thumb.done }}<span class="text-sm font-normal text-mute"> / {{ stat.covers }}</span></b><span class="text-xs text-mute">排队 {{ stat.thumb.queued }} · 缺失 <b :class="stat.thumb.missing ? 'text-warn' : ''">{{ stat.thumb.missing }}</b></span></li>
        <li class="card px-[18px] py-3.5"><p class="m-0 text-[13px] text-mute">动图</p><b class="mt-1 block text-2xl tabular-nums">{{ stat.anim.done }}</b><span class="text-xs text-mute">排队 {{ stat.anim.queued }} · 缺失 <b :class="stat.anim.missing ? 'text-warn' : ''">{{ stat.anim.missing }}</b> · 没有动画 {{ stat.anim.no_anim }}</span></li>
        <li class="card px-[18px] py-3.5"><p class="m-0 flex items-center text-[13px] text-mute"><span class="mr-1.5 inline-block h-2 w-2 rounded-full" :class="stat.worker_alive ? 'bg-ok' : 'bg-bad'" />后台队列</p><b class="mt-1 block text-2xl tabular-nums">{{ stat.queue_length }}</b><span class="text-xs" :class="stat.worker_alive ? 'text-mute' : 'text-bad'">{{ stat.worker_alive ? '处理线程在运行' : '处理线程没有运行' }}</span></li>
        <li class="card px-[18px] py-3.5"><p class="m-0 text-[13px] text-mute">占用空间</p><b class="mt-1 block text-2xl tabular-nums">{{ mb(stat.storage.thumb_bytes + stat.storage.anim_bytes) }}</b><span class="text-xs text-mute">缩略图 {{ mb(stat.storage.thumb_bytes) }} · 动图 {{ mb(stat.storage.anim_bytes) }}</span></li>
      </ul>

      <section class="card mt-3.5">
        <div class="flex flex-wrap items-center gap-2 border-b border-line px-3.5 py-3">
          <div class="seg"><button v-for="k in KINDS" :key="k[0]" :class="{ on: kind === k[0] }" @click="kind = k[0]">{{ k[1] }}</button></div>
          <div class="seg"><button v-for="s in statusTabs" :key="s[0]" :class="{ on: status === s[0] }" @click="status = s[0]">{{ s[1] }}</button></div>
          <span v-if="canWrite" class="flex flex-wrap gap-2 sm:ml-auto">
            <button class="btn" :disabled="!!busy || !(stat.thumb.missing + stat.anim.missing)" @click="retryAll(false)">重试缺失项</button>
            <button v-if="stat.anim.no_anim" class="btn" :disabled="!!busy" @click="retryAll(true)">连「没有动画」一起重试</button>
          </span>
        </div>
        <ATable :columns="columns" :rows="list?.items || []" :loading="!list" row-key="cover_path" empty-text="没有符合条件的封面">
          <template #cell-item="{ row: r }"><RouterLink :to="{ path: '/content', query: { id: r.item.id } }" class="font-medium text-ink no-underline hover:text-primary">{{ r.item.name }}</RouterLink></template>
          <template #cell-status="{ row: r }"><span class="tag" :class="STATUS_TAG[r.status]">{{ r.status_label }}</span></template>
          <template #cell-updated_at="{ row: r }"><span class="text-xs whitespace-nowrap text-mute">{{ r.updated_at ? formatTime(r.updated_at) : '—' }}</span></template>
          <template #cell-actions="{ row: r }"><button v-if="canWrite" class="btn btn-sm" :disabled="!!busy" @click="regen(r)">重新生成</button></template>
        </ATable>
        <div v-if="list" class="flex items-center border-t border-line px-[18px] py-3 text-xs text-mute">
          共 {{ list.total }} 个
          <button v-if="list.items.length < list.total" class="btn btn-sm ml-auto" @click="loadList(true)">加载更多</button>
        </div>
      </section>
    </template>
  </div>
</template>
