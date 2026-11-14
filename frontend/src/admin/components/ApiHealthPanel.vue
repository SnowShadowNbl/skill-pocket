<script setup>
import { ref, watch } from 'vue'
import { api, isCancelled } from '../../api'
import { toast } from '../../composables/toast'
import ALineChart from './ALineChart.vue'

// 接口健康：按路由统计请求量、5xx、慢接口；耗时是按分档估算的，所以带「约」
const days = ref(7)
const data = ref(null)
const DAYS = [[1, '24 小时'], [7, '7 天'], [30, '30 天']]
const SERIES = [{ key: 'requests', label: '请求', color: '#1e56d6' }, { key: 'errors_5xx', label: '5xx 错误', color: '#e5484d' }]
const ms = (v) => (v == null ? '未知' : `约 ${v} ms`)
const rate = (r) => (r == null ? '未知' : `${Math.round(r * 10000) / 100}%`)

watch(days, async () => {
  data.value = null
  try {
    data.value = await api(`/api/admin/api-health?days=${days.value}`)
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  }
}, { immediate: true })
</script>

<template>
  <div>
    <div class="mt-3 flex flex-wrap items-center gap-2">
      <div class="seg"><button v-for="d in DAYS" :key="d[0]" :class="{ on: days === d[0] }" @click="days = d[0]">{{ d[1] }}</button></div>
      <span v-if="data" class="ml-auto text-xs text-mute">{{ data.since }}</span>
    </div>
    <div v-if="!data" class="skeleton mt-3 h-60" />
    <template v-else>
      <ul class="m-0 mt-3 grid list-none grid-cols-2 gap-3.5 p-0 lg:grid-cols-4">
        <li class="card px-[18px] py-3.5"><p class="m-0 text-[13px] text-mute">请求数</p><b class="mt-1 block text-2xl tabular-nums">{{ data.totals.requests.toLocaleString() }}</b></li>
        <li class="card px-[18px] py-3.5" :class="data.totals.errors_5xx ? 'border-bad/40 bg-bad-soft' : ''"><p class="m-0 text-[13px]" :class="data.totals.errors_5xx ? 'text-bad' : 'text-mute'">5xx 错误</p><b class="mt-1 block text-2xl tabular-nums" :class="{ 'text-bad': data.totals.errors_5xx }">{{ data.totals.errors_5xx.toLocaleString() }}</b></li>
        <li class="card px-[18px] py-3.5"><p class="m-0 text-[13px] text-mute">错误率</p><b class="mt-1 block text-2xl tabular-nums" :class="{ 'text-mute': data.totals.error_rate == null }">{{ rate(data.totals.error_rate) }}</b></li>
        <li class="card px-[18px] py-3.5"><p class="m-0 text-[13px] text-mute">P95 耗时</p><b class="mt-1 block text-2xl tabular-nums" :class="{ 'text-mute': data.totals.p95_ms == null }">{{ ms(data.totals.p95_ms) }}</b></li>
      </ul>
      <section class="card mt-3.5">
        <div class="card-hd"><h2>请求趋势</h2></div>
        <div class="card-bd"><ALineChart :data="data.series" :series="SERIES" :height="170" /></div>
      </section>
      <div class="mt-3.5 grid gap-3.5 lg:grid-cols-2">
        <section class="card">
          <div class="card-hd"><h2>慢接口</h2><span class="text-xs text-mute">按 P95 · 至少 5 次请求</span></div>
          <p v-if="!data.slow.length" class="m-0 px-[18px] py-6 text-center text-[13px] text-mute">还没有足够的数据</p>
          <div v-else class="overflow-x-auto">
            <table class="tbl">
              <thead><tr><th>接口</th><th class="text-right">次数</th><th class="text-right">P50</th><th class="text-right">P95</th><th class="text-right">最大</th></tr></thead>
              <tbody><tr v-for="r in data.slow" :key="r.method + r.path"><td class="max-w-[260px] break-all"><span class="tag tag-gray mr-1.5">{{ r.method }}</span><span class="font-mono text-xs">{{ r.path }}</span></td><td class="text-right tabular-nums">{{ r.count }}</td><td class="text-right text-xs whitespace-nowrap tabular-nums">{{ ms(r.p50_ms) }}</td><td class="text-right text-xs font-semibold whitespace-nowrap tabular-nums">{{ ms(r.p95_ms) }}</td><td class="text-right text-xs whitespace-nowrap tabular-nums">{{ r.max_ms == null ? '未知' : `${r.max_ms} ms` }}</td></tr></tbody>
            </table>
          </div>
        </section>
        <section class="card">
          <div class="card-hd"><h2>出错接口</h2><span class="text-xs text-mute">有 5xx 的</span></div>
          <p v-if="!data.errors.length" class="m-0 px-[18px] py-6 text-center text-[13px] text-mute">没有 5xx 错误</p>
          <div v-else class="overflow-x-auto">
            <table class="tbl">
              <thead><tr><th>接口</th><th class="text-right">5xx</th><th class="text-right">4xx</th><th>最近</th></tr></thead>
              <tbody><tr v-for="r in data.errors" :key="r.method + r.path"><td class="max-w-[260px] break-all"><span class="tag tag-gray mr-1.5">{{ r.method }}</span><span class="font-mono text-xs">{{ r.path }}</span></td><td class="text-right font-semibold text-bad tabular-nums">{{ r.errors_5xx }}</td><td class="text-right tabular-nums text-mute">{{ r.errors_4xx }}</td><td class="text-xs whitespace-nowrap text-mute">{{ r.status }} · {{ r.last_at ? new Date(r.last_at).toLocaleString('zh-CN', { hour12: false, timeZone: 'Asia/Shanghai' }) : '' }}</td></tr></tbody>
            </table>
          </div>
        </section>
      </div>
    </template>
  </div>
</template>
