<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, isCancelled } from '../../api'
import { toast } from '../../composables/toast'
import ALineChart from './ALineChart.vue'

// AI 消耗：按功能 / 模型 / 用户 / 天汇总调用次数、token、延迟、失败，估算成本（没配单价的模型显示「未知」）
const route = useRoute()
const router = useRouter()
// 从数据分析下钻来时带 ?purpose=AI-x：只看这个功能
const purpose = computed(() => (typeof route.query.purpose === 'string' ? route.query.purpose : ''))
const clearPurpose = () => router.replace({ query: { ...route.query, purpose: undefined } })
const days = ref(30)
const group = ref('purpose')
// v3.3.89 成本口径：按最高价（保守，经营核算用）/ 按实际时段（峰谷、缓存命中）
const basis = ref('max')
const BASES = [['max', '按最高价'], ['actual', '按实际时段']]
const data = ref(null)
const ov = ref(null)
const GROUPS = [['purpose', '功能'], ['model', '模型'], ['user', '用户'], ['day', '按天']]

async function load() {
  data.value = null
  try {
    data.value = await api(`/api/admin/ai/usage?days=${days.value}&group=${group.value}&basis=${basis.value}${purpose.value ? `&purpose=${encodeURIComponent(purpose.value)}` : ''}`)
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  }
}
async function loadOverview() {
  try {
    ov.value = await api('/api/admin/ai/quota-overview')
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  }
}
watch([days, group, purpose, basis], load, { immediate: true })
loadOverview()

const num = (n) => (n == null ? '—' : Number(n).toLocaleString())
const tok = (n) => (n == null ? '—' : n >= 1e6 ? `${(n / 1e6).toFixed(2)} M` : n >= 1e3 ? `${(n / 1e3).toFixed(1)} K` : String(n))
const cost = (v) => (v == null ? '未知' : `¥${v.toFixed(v < 1 ? 3 : 2)}`)
const ms = (v) => (v == null ? '—' : `${Math.round(v)} ms`)
const failRate = (r) => (r.calls ? `${Math.round((r.fail / r.calls) * 1000) / 10}%` : '—')
const SERIES = [
  { key: 'calls', label: '调用次数', color: '#1e56d6' },
  { key: 'fail', label: '失败', color: '#e5484d' },
]
const chartData = computed(() => (data.value?.series || []).map((s) => ({ ...s, date: s.date })))
const totals = computed(() => data.value?.totals)
</script>

<template>
  <div>
    <ul v-if="ov" class="m-0 grid list-none grid-cols-2 gap-3.5 p-0 lg:grid-cols-6">
      <li class="card px-[18px] py-3.5"><p class="m-0 text-[13px] text-mute">有额度的用户</p><b class="mt-1 block text-2xl tabular-nums">{{ num(ov.users_with_quota) }}</b></li>
      <li class="card px-[18px] py-3.5"><p class="m-0 text-[13px] text-mute">额度余额合计</p><b class="mt-1 block text-2xl tabular-nums">{{ tok(ov.total_balance) }}</b></li>
      <li class="card px-[18px] py-3.5" :class="ov.low_balance_users ? 'border-warn/50 bg-warn-soft' : ''"><p class="m-0 text-[13px]" :class="ov.low_balance_users ? 'text-warn' : 'text-mute'">余额不足（&lt; {{ tok(ov.low_threshold) }}）</p><b class="mt-1 block text-2xl tabular-nums" :class="{ 'text-warn': ov.low_balance_users }">{{ num(ov.low_balance_users) }}</b></li>
      <li class="card px-[18px] py-3.5" :class="ov.exhausted_users ? 'border-bad/40 bg-bad-soft' : ''"><p class="m-0 text-[13px]" :class="ov.exhausted_users ? 'text-bad' : 'text-mute'">额度用完</p><b class="mt-1 block text-2xl tabular-nums" :class="{ 'text-bad': ov.exhausted_users }">{{ num(ov.exhausted_users) }}</b></li>
      <li class="card px-[18px] py-3.5"><p class="m-0 text-[13px] text-mute">待绑定微信</p><b class="mt-1 block text-2xl tabular-nums">{{ num(ov.needs_wechat_users) }}</b></li>
      <li class="card px-[18px] py-3.5"><p class="m-0 text-[13px] text-mute">今日调用</p><b class="mt-1 block text-2xl tabular-nums">{{ num(ov.today_calls) }}</b></li>
    </ul>

    <section class="card mt-3.5">
      <div class="card-hd">
        <h2>消耗</h2>
        <div class="seg ml-auto"><button v-for="b in BASES" :key="b[0]" :class="{ on: basis === b[0] }" @click="basis = b[0]">{{ b[1] }}</button></div>
        <div class="seg"><button v-for="d in [7, 30, 90]" :key="d" :class="{ on: days === d }" @click="days = d">{{ d }} 天</button></div>
      </div>
      <div v-if="!data" class="card-bd"><div class="skeleton h-52" /></div>
      <div v-else class="card-bd">
        <ul class="m-0 grid list-none grid-cols-2 gap-2.5 p-0 sm:grid-cols-5">
          <li class="rounded-lg bg-subtle px-3 py-2"><p class="m-0 text-xs text-mute">调用次数</p><b class="text-lg tabular-nums">{{ num(totals.calls) }}</b></li>
          <li class="rounded-lg px-3 py-2" :class="totals.fail ? 'bg-bad-soft' : 'bg-subtle'"><p class="m-0 text-xs" :class="totals.fail ? 'text-bad' : 'text-mute'">失败</p><b class="text-lg tabular-nums" :class="{ 'text-bad': totals.fail }">{{ num(totals.fail) }}</b></li>
          <li class="rounded-lg bg-subtle px-3 py-2"><p class="m-0 text-xs text-mute">输入 / 输出 token</p><b class="text-lg tabular-nums">{{ tok(totals.tokens_in) }} / {{ tok(totals.tokens_out) }}</b></li>
          <li class="rounded-lg bg-subtle px-3 py-2"><p class="m-0 text-xs text-mute">平均延迟</p><b class="text-lg tabular-nums">{{ ms(totals.avg_latency_ms) }}</b></li>
          <li class="rounded-lg bg-subtle px-3 py-2"><p class="m-0 text-xs text-mute">成本<span class="tag tag-gray ml-1 !h-[18px] !px-1.5 !text-[11px]">{{ basis === 'max' ? '最高价' : '实际时段' }}</span></p><b class="text-lg tabular-nums" :class="totals.est_cost_yuan == null ? 'text-mute' : ''">{{ cost(totals.est_cost_yuan) }}</b></li>
        </ul>
        <div class="mt-4"><ALineChart :data="chartData" :series="SERIES" :height="190" /></div>
      </div>
    </section>

    <section class="card mt-3.5">
      <p v-if="purpose" class="m-0 flex items-center gap-2 border-b border-line bg-primary-soft px-[18px] py-2 text-[13px] text-primary">只看功能：<b>{{ data?.items.find((x) => x.key === purpose)?.label || purpose }}</b><button class="ml-auto underline" @click="clearPurpose">去掉</button></p>
      <div class="card-hd"><h2>明细</h2><div class="seg ml-auto"><button v-for="g in GROUPS" :key="g[0]" :class="{ on: group === g[0] }" @click="group = g[0]">{{ g[1] }}</button></div></div>
      <div v-if="!data" class="card-bd"><div class="skeleton h-40" /></div>
      <p v-else-if="!data.items.length" class="empty">这段时间没有 AI 调用</p>
      <div v-else class="overflow-x-auto">
        <table class="tbl">
          <thead><tr><th>{{ GROUPS.find((g) => g[0] === group)[1] }}</th><th class="text-right">调用</th><th class="text-right">失败</th><th class="hidden text-right md:table-cell">输入 token</th><th class="hidden text-right md:table-cell">输出 token</th><th class="hidden text-right lg:table-cell">平均延迟</th><th class="text-right">估算成本</th></tr></thead>
          <tbody>
            <tr v-for="r in data.items" :key="r.key">
              <td class="font-medium">{{ r.label }}<span v-if="group === 'user' && r.key" class="ml-1.5 text-xs font-normal text-mute">#{{ r.key }}</span></td>
              <td class="text-right tabular-nums">{{ num(r.calls) }}</td>
              <td class="text-right tabular-nums" :class="r.fail ? 'text-bad' : 'text-mute'">{{ num(r.fail) }}<span v-if="r.fail" class="ml-1 text-xs">（{{ failRate(r) }}）</span></td>
              <td class="hidden text-right tabular-nums md:table-cell">{{ tok(r.tokens_in) }}</td>
              <td class="hidden text-right tabular-nums md:table-cell">{{ tok(r.tokens_out) }}</td>
              <td class="hidden text-right tabular-nums lg:table-cell">{{ ms(r.avg_latency_ms) }}</td>
              <td class="text-right tabular-nums" :class="r.est_cost_yuan == null ? 'text-mute' : ''">{{ cost(r.est_cost_yuan) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section v-if="ov?.top_users?.length" class="card mt-3.5">
      <div class="card-hd"><h2>近 30 天用量前 10</h2></div>
      <div class="overflow-x-auto"><table class="tbl">
        <thead><tr><th>用户</th><th class="text-right">近 30 天用量</th><th class="text-right">余额</th></tr></thead>
        <tbody>
          <tr v-for="u in ov.top_users" :key="u.user.id">
            <td class="max-w-[200px] break-words"><RouterLink :to="{ path: '/users', query: { id: u.user.id } }" class="hover:text-primary">{{ u.user.label }}</RouterLink></td>
            <td class="text-right tabular-nums">{{ tok(u.used_30d) }}</td>
            <td class="text-right tabular-nums" :class="u.balance <= 0 ? 'text-bad' : ''">{{ num(u.balance) }}</td>
          </tr>
        </tbody>
      </table></div>
    </section>
  </div>
</template>
