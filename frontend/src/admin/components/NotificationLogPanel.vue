<script setup>
import { ref, watch } from 'vue'
import { api, formatTime, isCancelled } from '../../api'
import { toast } from '../../composables/toast'
import { useQueryFilters } from '../composables/useQueryFilters'
import AFilterBar from './AFilterBar.vue'
import ATable from './ATable.vue'

// 站内消息发送记录：只保留 60 天；按类型看发送和已读
const data = ref(null)
const page = ref(1)
const { filters, params, activeCount, reset } = useQueryFilters({ kind: '', created: { from: '', to: '' } })
const KIND = (k) => [{ value: '', label: '全部类型' }, ...Object.entries(k || {}).map(([value, label]) => ({ value, label }))]
const fields = ref([
  { key: 'kind', type: 'select', label: '类型', options: KIND() },
  { key: 'created', type: 'daterange', label: '发送时间' },
])
const columns = [
  { key: 'at', label: '时间', mobile: 'sub' },
  { key: 'title', label: '消息', mobile: 'title' },
  { key: 'user', label: '收件人', mobile: 'meta' },
  { key: 'read', label: '已读', mobile: 'meta' },
  { key: 'source', label: '发送人', hideBelow: 'md', mobile: 'hide' },
]
const rate = (r) => (r == null ? '未知' : `${Math.round(r * 1000) / 10}%`)
const who = (s) => (typeof s === 'string' ? s : s?.label || '')

async function load(more = false) {
  page.value = more ? page.value + 1 : 1
  const p = new URLSearchParams(params.value)
  p.set('page', page.value)
  p.set('page_size', 30)
  try {
    const d = await api(`/api/admin/notifications?${p}`)
    fields.value[0].options = KIND(d.kinds)
    data.value = more ? { ...d, items: [...data.value.items, ...d.items], by_kind: d.by_kind } : d
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  }
}
watch(() => params.value.toString(), () => load(), { immediate: true })
</script>

<template>
  <div>
    <ul v-if="data?.by_kind.length" class="m-0 mt-3 grid list-none gap-3.5 p-0 sm:grid-cols-2 lg:grid-cols-4">
      <li v-for="k in data.by_kind" :key="k.kind" class="card px-[18px] py-3.5">
        <p class="m-0 text-[13px] text-mute">{{ k.label }}</p>
        <b class="mt-1 block text-2xl tabular-nums">{{ k.sent }}</b>
        <p class="m-0 mt-1 text-xs text-mute">已读 {{ k.read }} · {{ rate(k.read_rate) }}</p>
      </li>
    </ul>
    <section class="card mt-3.5">
      <AFilterBar :filters="filters" :fields="fields" :active-count="activeCount" @reset="reset" />
      <ATable :columns="columns" :rows="data?.items || []" :loading="!data" empty-text="没有站内消息记录">
        <template #cell-at="{ row: r }"><span class="text-xs whitespace-nowrap text-mute">{{ formatTime(r.at) }}</span></template>
        <template #cell-title="{ row: r }"><span class="tag tag-gray mr-1.5">{{ r.kind_label }}</span><b class="font-medium break-words">{{ r.title }}</b></template>
        <template #cell-user="{ row: r }"><router-link :to="{ path: '/users', query: { id: r.user.id } }" class="text-[13px] break-words text-primary no-underline">{{ r.user.label }}</router-link></template>
        <template #cell-read="{ row: r }"><span class="tag" :class="r.read_at ? 'tag-ok' : 'tag-gray'">{{ r.read_at ? '已读' : '未读' }}</span></template>
        <template #cell-source="{ row: r }"><span class="text-xs text-mute">{{ who(r.source) }}</span></template>
      </ATable>
      <div v-if="data" class="flex items-center border-t border-line px-[18px] py-3 text-xs text-mute">
        共 {{ data.total }} 条
        <span class="ml-3">站内消息只保留 {{ data.retention_days }} 天</span>
        <button v-if="data.items.length < data.total" class="btn btn-sm ml-auto" @click="load(true)">加载更多</button>
      </div>
    </section>
  </div>
</template>
