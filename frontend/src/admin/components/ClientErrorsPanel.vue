<script setup>
import { ref, watch } from 'vue'
import { api, formatTime, isCancelled } from '../../api'
import { toast } from '../../composables/toast'
import { useQueryFilters } from '../composables/useQueryFilters'
import AFilterBar from './AFilterBar.vue'
import ALineChart from './ALineChart.vue'
import ATable from './ATable.vue'

// 客户端报错：网页和小程序自动上报，同一类错误合并计数；趋势按「最近一次出现」归档，是近似值
const data = ref(null)
const sum = ref(null)
const page = ref(1)
const open = ref(null)
const { filters, params, activeCount, reset } = useQueryFilters({ q: '', client: '', kind: '', version: '', days: '30' })
const CLIENTS = [{ value: '', label: '全部端' }, { value: 'web-pc', label: '网页 · 电脑' }, { value: 'web-mobile', label: '网页 · 手机' }, { value: 'miniprogram', label: '小程序' }, { value: 'unknown', label: '未知' }]
const fields = ref([
  { key: 'q', type: 'search', label: '错误信息或页面' },
  { key: 'client', type: 'select', label: '端', options: CLIENTS },
  { key: 'kind', type: 'select', label: '类型', options: [{ value: '', label: '全部类型' }] },
  { key: 'days', type: 'select', label: '时间', options: [{ value: '1', label: '近 24 小时' }, { value: '7', label: '近 7 天' }, { value: '30', label: '近 30 天' }, { value: '90', label: '近 90 天' }] },
])
const columns = [
  { key: 'message', label: '错误', mobile: 'title' },
  { key: 'client', label: '端 / 版本', mobile: 'meta' },
  { key: 'count', label: '次数', align: 'right', mobile: 'meta' },
  { key: 'last', label: '最近', hideBelow: 'md', mobile: 'sub' },
]
const SERIES = [{ key: 'count', label: '报错', color: '#e5484d' }]

async function load(more = false) {
  page.value = more ? page.value + 1 : 1
  const p = new URLSearchParams(params.value)
  p.set('page', page.value)
  p.set('page_size', 30)
  try {
    const d = await api(`/api/admin/client-errors?${p}`)
    fields.value[2].options = [{ value: '', label: '全部类型' }, ...Object.entries(d.kinds || {}).map(([value, label]) => ({ value, label }))]
    data.value = more ? { ...d, items: [...data.value.items, ...d.items] } : d
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  }
}
watch(() => params.value.toString(), () => load(), { immediate: true })
watch(() => filters.days, async () => {
  try { sum.value = await api(`/api/admin/client-errors/summary?days=${filters.days || 30}`) } catch { /* 汇总拿不到不影响列表 */ }
}, { immediate: true })
</script>

<template>
  <div>
    <template v-if="sum">
      <ul class="m-0 mt-3 grid list-none grid-cols-2 gap-3.5 p-0 lg:grid-cols-4">
        <li class="card px-[18px] py-3.5"><p class="m-0 text-[13px] text-mute">报错次数</p><b class="mt-1 block text-2xl tabular-nums">{{ sum.total }}</b></li>
        <li class="card px-[18px] py-3.5"><p class="m-0 text-[13px] text-mute">不同的错误</p><b class="mt-1 block text-2xl tabular-nums">{{ sum.distinct }}</b></li>
        <li v-for="c in sum.by_client.slice(0, 2)" :key="c.client" class="card px-[18px] py-3.5"><p class="m-0 text-[13px] text-mute">{{ c.label }}</p><b class="mt-1 block text-2xl tabular-nums">{{ c.count }}</b></li>
      </ul>
      <div v-if="sum.total" class="mt-3.5 grid gap-3.5 lg:grid-cols-[2fr_1fr]">
        <section class="card">
          <div class="card-hd"><h2>趋势</h2><span class="text-xs text-mute">按最近一次出现的日期，近似值</span></div>
          <div class="card-bd"><ALineChart :data="sum.series" :series="SERIES" :height="150" /></div>
        </section>
        <section class="card">
          <div class="card-hd"><h2>出错最多的页面</h2></div>
          <ul class="m-0 list-none p-0"><li v-for="p in sum.by_page.slice(0, 6)" :key="p.page" class="flex gap-2 border-b border-dashed border-line px-[18px] py-2 text-[13px] last:border-0"><span class="min-w-0 flex-1 font-mono text-xs break-all">{{ p.page || '未知页面' }}</span><b class="tabular-nums">{{ p.count }}</b></li></ul>
        </section>
      </div>
    </template>

    <section class="card mt-3.5">
      <AFilterBar :filters="filters" :fields="fields" :active-count="activeCount - (filters.days !== '30' ? 1 : 0)" @reset="reset" />
      <ATable :columns="columns" :rows="data?.items || []" :loading="!data" empty-text="这段时间没有报错">
        <template #cell-message="{ row: r }">
          <button class="block w-full cursor-pointer border-0 bg-transparent p-0 text-left" @click="open = open === r.id ? null : r.id">
            <span class="tag tag-gray mr-1.5">{{ r.kind_label }}</span><b class="font-medium break-words">{{ r.message }}</b>
            <span class="block text-xs break-all text-mute">{{ r.page || '未知页面' }}<template v-if="r.user"> · {{ r.user.label }}</template></span>
          </button>
          <div v-if="open === r.id" class="mt-2 rounded-lg bg-subtle p-3 text-xs">
            <pre v-if="r.stack" class="m-0 max-h-60 overflow-auto font-mono break-all whitespace-pre-wrap">{{ r.stack }}</pre>
            <p v-else class="m-0 text-mute">没有调用栈</p>
            <p class="m-0 mt-2 break-all text-mute">{{ r.user_agent || '未知设备' }} · 影响 {{ r.users }} 位用户 · 首次 {{ formatTime(r.first_at) }}</p>
          </div>
        </template>
        <template #cell-client="{ row: r }"><span class="text-xs whitespace-nowrap">{{ r.client_label }}<template v-if="r.version"> {{ r.version }}</template></span></template>
        <template #cell-count="{ row: r }"><b class="tabular-nums">{{ r.count }}</b></template>
        <template #cell-last="{ row: r }"><span class="text-xs whitespace-nowrap text-mute">{{ formatTime(r.last_at) }}</span></template>
      </ATable>
      <div v-if="data" class="flex items-center border-t border-line px-[18px] py-3 text-xs text-mute">
        共 {{ data.total }} 类
        <button v-if="data.items.length < data.total" class="btn btn-sm ml-auto" @click="load(true)">加载更多</button>
      </div>
    </section>
  </div>
</template>
