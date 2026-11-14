<script setup>
import { ref } from 'vue'
import { api, formatTime, isCancelled } from '../../api'
import { toast } from '../../composables/toast'
import ATable from './ATable.vue'

// 每日推送执行记录：每天 08:30 一次，保留最近 60 次；还没有记录的字段显示「未知」
const data = ref(null)
const page = ref(1)
const columns = [
  { key: 'started', label: '开始时间', mobile: 'title' },
  { key: 'ok', label: '结果', mobile: 'meta' },
  { key: 'sent', label: '发出', mobile: 'meta' },
  { key: 'detail', label: '明细', hideBelow: 'md', mobile: 'sub' },
]
const n = (v) => (v == null ? '未知' : v)
const secs = (r) => (r.finished_at ? Math.max(0, Math.round((new Date(r.finished_at) - new Date(r.started_at)) / 1000)) : null)

async function load(more = false) {
  page.value = more ? page.value + 1 : 1
  try {
    const d = await api(`/api/admin/push-runs?page=${page.value}&page_size=30`)
    data.value = more ? { ...d, items: [...data.value.items, ...d.items] } : d
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  }
}
load()
</script>

<template>
  <section class="card mt-3">
    <ATable :columns="columns" :rows="data?.items || []" :loading="!data" :empty-text="data?.since ? `还没有执行记录（${data.since}，每天 08:30 推送）` : '还没有执行记录'">
      <template #cell-started="{ row: r }"><b class="font-medium whitespace-nowrap">{{ formatTime(r.started_at) }}</b><span v-if="secs(r) != null" class="ml-2 text-xs text-mute">用时 {{ secs(r) }} 秒</span><span v-if="r.error" class="block text-xs text-bad break-words">{{ r.error }}</span></template>
      <template #cell-ok="{ row: r }"><span class="tag" :class="r.ok ? 'tag-ok' : 'tag-bad'">{{ r.ok ? '成功' : '失败' }}</span></template>
      <template #cell-sent="{ row: r }"><b class="tabular-nums">{{ n(r.sent) }}</b></template>
      <template #cell-detail="{ row: r }"><span class="text-[13px] text-ink-2">上新 {{ n(r.digests) }} · 版本提醒 {{ n(r.releases) }} · 失败 {{ n(r.failed) }}</span></template>
    </ATable>
    <div v-if="data" class="flex items-center border-t border-line px-[18px] py-3 text-xs text-mute">
      共 {{ data.total }} 次
      <button v-if="data.items.length < data.total" class="btn btn-sm ml-auto" @click="load(true)">加载更多</button>
    </div>
  </section>
</template>
