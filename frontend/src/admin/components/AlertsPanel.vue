<script setup>
import { computed, ref, watch } from 'vue'
import { api, formatTime, isCancelled } from '../../api'
import { toast } from '../../composables/toast'
import { runBulk } from '../composables/bulk'
import { onActionError } from '../composables/handled'
import { askReason } from '../composables/reason'
import { can } from '../composables/usePermissions'
import { useQueryFilters } from '../composables/useQueryFilters'
import { useSelection } from '../composables/useSelection'
import ABulkBar from './ABulkBar.vue'
import AFilterBar from './AFilterBar.vue'
import ATable from './ATable.vue'

// 告警：同一件事只保留一条（持续成立时更新最近时间），条件消失后自动恢复；可以确认、关闭。新告警和恢复会通过站内消息通知管理员
const emit = defineEmits(['changed'])
const { filters, params, activeCount, reset } = useQueryFilters({ status: '', level: '', source: '' })
const data = ref(null)
const page = ref(1)
const canWrite = computed(() => can('resources', 'w'))
const TABS = [['', '未恢复'], ['open', '待处理'], ['acked', '已确认'], ['resolved', '已恢复'], ['all', '全部']]
const LEVEL = { critical: ['严重', 'tag-bad'], warn: ['警告', 'tag-warn'], info: ['提示', 'tag-blue'] }
const STATUS = { open: 'tag-warn', acked: 'tag-blue', resolved: 'tag-ok' }
const fields = [
  { key: 'level', type: 'select', label: '级别', options: [{ value: '', label: '全部级别' }, { value: 'critical', label: '严重' }, { value: 'warn', label: '警告' }, { value: 'info', label: '提示' }] },
  { key: 'source', type: 'select', label: '来源', options: [{ value: '', label: '全部来源' }, { value: 'resource', label: '资源' }, { value: 'backup', label: '备份' }, { value: 'risk', label: '风控' }] },
]
const columns = [
  { key: 'title', label: '告警', mobile: 'title' },
  { key: 'level', label: '级别', mobile: 'meta' },
  { key: 'status', label: '状态', mobile: 'meta' },
  { key: 'time', label: '首次 / 最近', hideBelow: 'md', mobile: 'sub' },
  { key: 'actions', label: '', align: 'right', mobile: 'action' },
]
const sel = useSelection({ rows: computed(() => data.value?.items || []), total: computed(() => data.value?.total || 0), params, selectable: (a) => a.status !== 'resolved' })

async function load(more = false) {
  page.value = more ? page.value + 1 : 1
  const p = new URLSearchParams(params.value)
  p.set('status', filters.status || 'active')
  p.set('page', page.value)
  p.set('page_size', 30)
  try {
    const d = await api(`/api/admin/alerts?${p}`)
    data.value = more ? { ...d, items: [...data.value.items, ...d.items] } : d
    emit('changed')
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  }
}
watch(() => params.value.toString(), () => load(), { immediate: true })

async function act(a, action) {
  let reason = ''
  if (action === 'resolve') {
    reason = await askReason({ title: `关闭告警「${a.title}」`, impact: '关闭后如果条件仍然成立，会新开一条告警', templates: ['已处理', '已知问题，暂不处理', '误报'], okText: '关闭' })
    if (reason === null) return
  }
  try {
    await api(`/api/admin/alerts/${a.id}/${action}`, { method: 'POST', body: { reason, expected_status: a.status } })
    toast(action === 'ack' ? '已确认' : '已关闭', 'success')
    await load()
  } catch (e) {
    await onActionError(e, load)
  }
}
const bulkActions = [
  { key: 'ack', label: '确认', icon: 'check', run: (scope, reason) => runBulk('/api/admin/alerts/bulk', { action: 'ack', scope: { ids: scope.ids || [] }, reason }) },
  { key: 'resolve', label: '关闭', icon: 'x', danger: true,
    reason: { title: '批量关闭告警', impact: (n) => `将关闭 ${n} 条告警`, templates: ['已处理', '已知问题，暂不处理', '误报'], okText: '关闭' },
    run: (scope, reason) => runBulk('/api/admin/alerts/bulk', { action: 'resolve', scope: { ids: scope.ids || [] }, reason }) },
]
const resolvedBy = (a) => (a.resolved_by === 'auto' ? '自动恢复' : a.resolved_by?.label || '')
</script>

<template>
  <div>
    <section class="card mt-3">
      <div class="flex flex-wrap items-center gap-2 border-b border-line px-3.5 py-3">
        <div class="seg flex-wrap">
          <button v-for="t in TABS" :key="t[0]" :class="{ on: filters.status === t[0] }" @click="filters.status = t[0]">
            {{ t[1] }}<b v-if="data && ['open', 'acked', 'resolved'].includes(t[0]) && data.counts[t[0]]" class="ml-1 tabular-nums" :class="filters.status === t[0] ? '' : t[0] === 'open' ? 'text-bad' : 'text-mute'">{{ data.counts[t[0]] }}</b>
          </button>
        </div>
      </div>
      <AFilterBar :filters="filters" :fields="fields" :active-count="activeCount - (filters.status ? 1 : 0)" @reset="reset" />
      <ATable :columns="columns" :rows="data?.items || []" :loading="!data" :selection="canWrite ? sel : null" :empty-text="filters.status === '' ? '没有未恢复的告警' : '没有告警'">
        <template #cell-title="{ row: a }">
          <b class="block font-medium">{{ a.title }}</b>
          <span class="block max-w-[520px] text-xs break-words text-ink-2">{{ a.detail }}</span>
          <span v-if="a.status === 'resolved'" class="block text-xs text-mute">已恢复 {{ formatTime(a.resolved_at) }} · {{ resolvedBy(a) }}</span>
          <span v-else-if="a.status === 'acked' && a.acked_by" class="block text-xs text-mute">{{ a.acked_by.label }} 于 {{ formatTime(a.acked_at) }} 确认</span>
        </template>
        <template #cell-level="{ row: a }"><span class="tag" :class="LEVEL[a.level]?.[1]">{{ LEVEL[a.level]?.[0] || a.level }}</span></template>
        <template #cell-status="{ row: a }"><span class="tag" :class="STATUS[a.status]">{{ a.status_label }}</span></template>
        <template #cell-time="{ row: a }"><span class="text-xs whitespace-nowrap text-mute">{{ formatTime(a.first_at) }}<br />{{ formatTime(a.last_at) }}</span></template>
        <template #cell-actions="{ row: a }">
          <span v-if="canWrite && a.status !== 'resolved'" class="flex justify-end gap-1.5">
            <button v-if="a.status === 'open'" class="btn btn-sm" @click="act(a, 'ack')">确认</button>
            <button class="btn btn-sm btn-danger" @click="act(a, 'resolve')">关闭</button>
          </span>
        </template>
      </ATable>
      <div v-if="data" class="flex items-center border-t border-line px-[18px] py-3 text-xs text-mute">
        共 {{ data.total }} 条
        <button v-if="data.items.length < data.total" class="btn btn-sm ml-auto" @click="load(true)">加载更多</button>
      </div>
    </section>
    <ABulkBar v-if="canWrite" :selection="sel" :actions="bulkActions" noun="条告警" @done="load()" />
  </div>
</template>
