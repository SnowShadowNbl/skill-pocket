<script setup>
import { ref, watch } from 'vue'
import { api, formatTime, isCancelled } from '../../api'
import { toast } from '../../composables/toast'
import { useQueryFilters } from '../composables/useQueryFilters'
import AFilterBar from './AFilterBar.vue'
import ALineChart from './ALineChart.vue'
import ATable from './ATable.vue'

// 邮件发送记录：目前只发验证码邮件；退信和单封耗时没有记录，显示「未知」
const data = ref(null)
const stats = ref(null)
const page = ref(1)
const { filters, params, activeCount, reset } = useQueryFilters({ q: '', purpose: '', status: '', created: { from: '', to: '' } })
const PURPOSE = (p) => [{ value: '', label: '全部用途' }, ...Object.entries(p || {}).map(([value, label]) => ({ value, label }))]
const fields = ref([
  { key: 'q', type: 'search', label: '邮箱或失败原因' },
  { key: 'purpose', type: 'select', label: '用途', options: PURPOSE() },
  { key: 'status', type: 'select', label: '结果', options: [{ value: '', label: '全部结果' }, { value: 'sent', label: '已发送' }, { value: 'failed', label: '发送失败' }] },
  { key: 'created', type: 'daterange', label: '发送时间' },
])
const columns = [
  { key: 'at', label: '时间', mobile: 'sub' },
  { key: 'email', label: '邮箱', mobile: 'title' },
  { key: 'purpose', label: '用途', mobile: 'meta' },
  { key: 'status', label: '结果', mobile: 'meta' },
  { key: 'channel', label: '通道', hideBelow: 'md', mobile: 'hide' },
]
const SERIES = [{ key: 'sent', label: '已发送', color: '#1e56d6' }, { key: 'failed', label: '失败', color: '#e5484d' }]
const rate = (r) => (r == null ? '未知' : `${Math.round(r * 1000) / 10}%`)

async function load(more = false) {
  page.value = more ? page.value + 1 : 1
  const p = new URLSearchParams(params.value)
  p.set('page', page.value)
  p.set('page_size', 30)
  try {
    const d = await api(`/api/admin/emails?${p}`)
    fields.value[1].options = PURPOSE(d.purposes)
    data.value = more ? { ...d, items: [...data.value.items, ...d.items] } : d
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  }
}
watch(() => params.value.toString(), () => load(), { immediate: true })
api('/api/admin/emails/stats?days=30').then((s) => (stats.value = s)).catch(() => {})
</script>

<template>
  <div>
    <ul class="m-0 mt-3 grid list-none grid-cols-2 gap-3.5 p-0 lg:grid-cols-4">
      <li class="card px-[18px] py-3.5"><p class="m-0 text-[13px] text-mute">近 30 天已发送</p><b class="mt-1 block text-2xl tabular-nums">{{ stats ? stats.sent : '—' }}</b></li>
      <li class="card px-[18px] py-3.5" :class="stats?.failed ? 'border-bad/40 bg-bad-soft' : ''"><p class="m-0 text-[13px]" :class="stats?.failed ? 'text-bad' : 'text-mute'">发送失败</p><b class="mt-1 block text-2xl tabular-nums" :class="{ 'text-bad': stats?.failed }">{{ stats ? stats.failed : '—' }}</b></li>
      <li class="card px-[18px] py-3.5"><p class="m-0 text-[13px] text-mute">失败率</p><b class="mt-1 block text-2xl tabular-nums">{{ stats ? rate(stats.fail_rate) : '—' }}</b></li>
      <li class="card px-[18px] py-3.5"><p class="m-0 text-[13px] text-mute">退信</p><b class="mt-1 block text-2xl text-mute">未知</b></li>
    </ul>
    <section v-if="stats" class="card mt-3.5">
      <div class="card-hd"><h2>每日发送</h2></div>
      <div class="card-bd">
        <ALineChart :data="stats.series" :series="SERIES" :height="170" />
        <ul v-if="stats.by_purpose.length" class="m-0 mt-3 flex list-none flex-wrap gap-2 p-0"><li v-for="p in stats.by_purpose" :key="p.purpose" class="tag tag-gray">{{ p.label }} {{ p.sent }}<template v-if="p.failed">（失败 {{ p.failed }}）</template></li></ul>
      </div>
    </section>
    <section class="card mt-3.5">
      <AFilterBar :filters="filters" :fields="fields" :active-count="activeCount" @reset="reset" />
      <ATable :columns="columns" :rows="data?.items || []" :loading="!data" empty-text="没有邮件记录">
        <template #cell-at="{ row: r }"><span class="text-xs whitespace-nowrap text-mute">{{ formatTime(r.at) }}</span></template>
        <template #cell-email="{ row: r }">
          <b class="block font-mono text-[13px] font-medium break-all">{{ r.email }}</b>
          <span v-if="r.user" class="block text-xs text-mute break-words">{{ r.user.label }}</span>
          <span v-if="r.error" class="block text-xs text-bad break-words">{{ r.error }}</span>
        </template>
        <template #cell-purpose="{ row: r }"><span class="tag tag-gray">{{ r.purpose_label }}</span></template>
        <template #cell-status="{ row: r }"><span class="tag" :class="r.status === 'sent' ? 'tag-ok' : 'tag-bad'">{{ r.status === 'sent' ? '已发送' : '失败' }}</span></template>
        <template #cell-channel="{ row: r }"><span class="text-xs text-mute">{{ r.channel === 'ses' ? '邮件服务' : r.channel === 'console' ? '本地输出' : r.channel }}</span></template>
      </ATable>
      <div v-if="data" class="flex items-center border-t border-line px-[18px] py-3 text-xs text-mute">
        共 {{ data.total }} 封
        <button v-if="data.items.length < data.total" class="btn btn-sm ml-auto" @click="load(true)">加载更多</button>
      </div>
    </section>
  </div>
</template>
