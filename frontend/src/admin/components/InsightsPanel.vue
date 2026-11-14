<script setup>
import { computed, ref, watch } from 'vue'
import { api, isCancelled } from '../../api'
import { toast } from '../../composables/toast'
import { useDrill } from '../composables/drill'
import AExport from './AExport.vue'
import ALineChart from './ALineChart.vue'
import ASelect from './ASelect.vue'

// 数据分析：增长与活跃、内容表现、搜索质量、AI 功能效果；可按端拆分，指标可点进明细，表格可导出
const go = useDrill()
const sub = ref('growth')
const days = ref(30)
const channel = ref('')
const sort = ref('views')
const data = ref(null)
const SUBS = [['growth', '增长与活跃'], ['content', '内容表现'], ['search', '搜索质量'], ['ai', 'AI 功能']]
const DAYS = [[7, '7 天'], [30, '30 天'], [90, '90 天']]
const CHANNELS = [{ value: '', label: '全部端' }, { value: 'web-pc', label: 'PC 网页' }, { value: 'web-mobile', label: '手机网页' }, { value: 'miniprogram', label: '小程序' }, { value: 'unknown', label: '未知' }]
const SORTS = [{ value: 'views', label: '按浏览' }, { value: 'favorites', label: '按收藏' }, { value: 'copies', label: '按复制指令' }, { value: 'compares', label: '按对比' }, { value: 'outbound', label: '按跳转源站' }, { value: 'shares', label: '按分享' }]

const query = computed(() => {
  const p = new URLSearchParams({ days: days.value })
  if (channel.value && sub.value !== 'ai') p.set('channel', channel.value)
  if (sub.value === 'content') p.set('sort', sort.value)
  if (sub.value === 'content' || sub.value === 'search') p.set('limit', 50)
  return p
})
const exportParams = computed(() => {
  const p = new URLSearchParams(query.value)
  p.set('format', 'csv')
  return p
})

let seq = 0
watch([sub, days, channel, sort], async () => {
  const my = ++seq
  data.value = null
  try {
    const d = await api(`/api/admin/insights/${sub.value}?${query.value}`)
    if (my === seq) data.value = d
  } catch (e) {
    if (my === seq && !isCancelled(e)) toast(e.message, 'error')
  }
}, { immediate: true })

const n = (v) => (v == null ? '未知' : v.toLocaleString())
const pct = (r) => (r == null ? '未知' : `${Math.round(r * 1000) / 10}%`)
const retention = (r, pending) => (pending ? '待观察' : pct(r))
const secs = (v) => (v == null ? '未知' : v >= 60 ? `${Math.round(v / 60)} 分钟` : `${Math.round(v)} 秒`)
const ms = (v) => (v == null ? '未知' : v >= 1000 ? `${(v / 1000).toFixed(1)} 秒` : `${v} 毫秒`)
const GROWTH = [{ key: 'new_users', label: '新增账号' }, { key: 'active_users', label: '活跃账号' }, { key: 'active_devices', label: '活跃设备（不等于人数）' }]
const GS = [{ key: 'new_users', label: '新增', color: '#1e56d6' }, { key: 'active_users', label: '活跃账号', color: '#16a34a' }, { key: 'returning_users', label: '回访', color: '#d97706' }]
const CONTENT = [['views', '浏览'], ['favorites', '收藏'], ['copies', '复制指令'], ['compares', '对比'], ['outbound', '跳转源站'], ['shares', '分享']]
const TASK = { compare: 'AI 对比', finder: '查找', screenshot: '截图识别' }
</script>

<template>
  <div>
    <div class="mt-3 flex flex-wrap items-center gap-2">
      <div class="seg max-w-full overflow-x-auto [&>button]:shrink-0 [&>button]:whitespace-nowrap"><button v-for="t in SUBS" :key="t[0]" :class="{ on: sub === t[0] }" @click="sub = t[0]">{{ t[1] }}</button></div>
      <div class="seg"><button v-for="d in DAYS" :key="d[0]" :class="{ on: days === d[0] }" @click="days = d[0]">{{ d[1] }}</button></div>
      <div v-if="sub !== 'ai'" class="w-36"><ASelect v-model="channel" :options="CHANNELS" label="端" /></div>
      <div v-if="sub === 'content'" class="w-36"><ASelect v-model="sort" :options="SORTS" label="排序" /></div>
      <span v-if="sub === 'content' || sub === 'search'" class="ml-auto"><AExport :endpoint="`/api/admin/insights/${sub}`" :params="exportParams" :count="sub === 'content' ? data?.items.length : data?.terms.length" /></span>
    </div>
    <div v-if="!data" class="skeleton mt-3 h-60" />

    <template v-else-if="sub === 'growth'">
      <ul class="m-0 mt-3 grid list-none grid-cols-2 gap-3.5 p-0 lg:grid-cols-5">
        <li v-for="m in GROWTH" :key="m.key" class="card px-[18px] py-3.5"><p class="m-0 text-[13px] text-mute">{{ m.label }}</p><b class="mt-1 block text-2xl tabular-nums">{{ n(data.totals[m.key]) }}</b></li>
        <li class="card px-[18px] py-3.5"><p class="m-0 text-[13px] text-mute">次日留存</p><b class="mt-1 block text-2xl tabular-nums" :class="{ 'text-mute': data.totals.retention_d1 == null }">{{ retention(data.totals.retention_d1, data.totals.retention_d1_pending) }}</b><p class="m-0 mt-0.5 text-xs text-mute">{{ data.totals.cohort_d1 }} 人</p></li>
        <li class="card px-[18px] py-3.5"><p class="m-0 text-[13px] text-mute">7 日留存</p><b class="mt-1 block text-2xl tabular-nums" :class="{ 'text-mute': data.totals.retention_d7 == null }">{{ retention(data.totals.retention_d7, data.totals.retention_d7_pending) }}</b><p class="m-0 mt-0.5 text-xs text-mute">{{ data.totals.cohort_d7 }} 人</p></li>
      </ul>
      <section class="card mt-3.5"><div class="card-hd"><h2>每日趋势</h2></div><div class="card-bd"><ALineChart :data="data.series" :series="GS" :height="190" /></div></section>
      <section v-if="data.by_channel" class="card mt-3.5">
        <div class="card-hd"><h2>各端</h2></div>
        <div class="overflow-x-auto"><table class="tbl">
          <thead><tr><th>端</th><th class="text-right">新增</th><th class="text-right">活跃账号</th><th class="text-right">活跃设备</th></tr></thead>
          <tbody><tr v-for="c in data.by_channel" :key="c.channel" class="cursor-pointer hover:bg-subtle" @click="go(c.drill)"><td class="font-medium">{{ c.label }}</td><td class="text-right tabular-nums">{{ n(c.new_users) }}</td><td class="text-right tabular-nums">{{ n(c.active_users) }}</td><td class="text-right tabular-nums">{{ n(c.active_devices) }}</td></tr></tbody>
        </table></div>
      </section>
    </template>

    <template v-else-if="sub === 'content'">
      <ul class="m-0 mt-3 grid list-none grid-cols-2 gap-3.5 p-0 lg:grid-cols-3">
        <li v-for="c in CONTENT.slice(0, 4)" :key="c[0]" class="card px-[18px] py-3.5"><p class="m-0 text-[13px] text-mute">{{ c[1] }}</p><b class="mt-1 block text-2xl tabular-nums">{{ n(data.totals[c[0]]) }}</b></li>
        <li class="card px-[18px] py-3.5"><p class="m-0 text-[13px] text-mute">被浏览过的条目</p><b class="mt-1 block text-2xl tabular-nums">{{ n(data.totals.viewed_items) }}</b><p class="m-0 mt-0.5 text-xs text-mute">共 {{ n(data.totals.published_items) }} 个，{{ n(data.totals.never_viewed_items) }} 个没人看过</p></li>
        <li class="card px-[18px] py-3.5"><p class="m-0 text-[13px] text-mute">新增收藏</p><b class="mt-1 block text-2xl tabular-nums">{{ n(data.totals.new_favorites) }}</b></li>
      </ul>
      <section class="card mt-3.5">
        <div class="overflow-x-auto"><table class="tbl">
          <thead><tr><th>条目</th><th v-for="c in CONTENT" :key="c[0]" class="text-right whitespace-nowrap" :class="{ 'hidden md:table-cell': c[0] === 'outbound' || c[0] === 'shares' }">{{ c[1] }}</th><th class="hidden text-right md:table-cell">收藏率</th></tr></thead>
          <tbody>
            <tr v-if="!data.items.length"><td colspan="8" class="py-8 text-center text-mute">这段时间没有数据</td></tr>
            <tr v-for="r in data.items" :key="r.item.id" class="cursor-pointer hover:bg-subtle" @click="go(r.drill)">
              <td class="max-w-[220px] font-medium break-words">{{ r.item.name }}<span v-if="r.item.status !== 'published'" class="tag tag-gray ml-1.5">未上线</span></td>
              <td v-for="c in CONTENT" :key="c[0]" class="text-right tabular-nums" :class="{ 'hidden md:table-cell': c[0] === 'outbound' || c[0] === 'shares' }">{{ n(r[c[0]]) }}</td>
              <td class="hidden text-right tabular-nums md:table-cell">{{ pct(r.favorite_rate) }}</td>
            </tr>
          </tbody>
        </table></div>
      </section>
    </template>

    <template v-else-if="sub === 'search'">
      <ul class="m-0 mt-3 grid list-none grid-cols-2 gap-3.5 p-0 lg:grid-cols-4">
        <li class="card px-[18px] py-3.5"><p class="m-0 text-[13px] text-mute">搜索次数</p><b class="mt-1 block text-2xl tabular-nums">{{ n(data.totals.searches) }}</b></li>
        <li class="card px-[18px] py-3.5"><p class="m-0 text-[13px] text-mute">不同的搜索词</p><b class="mt-1 block text-2xl tabular-nums">{{ n(data.totals.distinct_terms) }}</b></li>
        <li class="card px-[18px] py-3.5"><p class="m-0 text-[13px] text-mute">点击率</p><b class="mt-1 block text-2xl tabular-nums" :class="{ 'text-mute': data.totals.click_rate == null }">{{ pct(data.totals.click_rate) }}</b></li>
        <li class="card cursor-pointer px-[18px] py-3.5" :class="data.totals.empty_terms ? 'border-warn/50 bg-warn-soft' : ''" @click="go(data.drill)"><p class="m-0 text-[13px]" :class="data.totals.empty_terms ? 'text-warn' : 'text-mute'">无结果的词</p><b class="mt-1 block text-2xl tabular-nums" :class="{ 'text-warn': data.totals.empty_terms }">{{ n(data.totals.empty_terms) }}</b></li>
      </ul>
      <section class="card mt-3.5"><div class="card-hd"><h2>每日搜索</h2></div><div class="card-bd"><ALineChart :data="data.series" :series="[{ key: 'searches', label: '搜索', color: '#1e56d6' }]" :height="150" /></div></section>
      <section v-if="data.empty.length" class="card mt-3.5">
        <div class="card-hd"><h2>还没补收录的无结果搜索</h2></div>
        <ul class="m-0 list-none p-0"><li v-for="e in data.empty" :key="e.id" class="flex items-center gap-2 border-b border-dashed border-line px-[18px] py-2 text-[13px] last:border-0"><b class="min-w-0 flex-1 break-words">{{ e.term }}</b><span class="tabular-nums text-mute">{{ e.empty_count }} 次</span></li></ul>
      </section>
      <section class="card mt-3.5">
        <div class="card-hd"><h2>高频搜索</h2></div>
        <div class="overflow-x-auto"><table class="tbl">
          <thead><tr><th>搜索词</th><th class="text-right">次数</th><th class="text-right">点击率</th><th class="hidden text-right md:table-cell">后续操作率</th><th class="hidden text-right md:table-cell">无结果</th></tr></thead>
          <tbody>
            <tr v-if="!data.terms.length"><td colspan="5" class="py-8 text-center text-mute">这段时间没有搜索</td></tr>
            <tr v-for="t in data.terms" :key="t.term" class="cursor-pointer hover:bg-subtle" @click="go(t.drill)"><td class="max-w-[260px] break-words">{{ t.term }}<span v-if="t.blocked" class="tag tag-gray ml-1.5">已屏蔽</span></td><td class="text-right tabular-nums">{{ t.searches }}</td><td class="text-right tabular-nums">{{ pct(t.click_rate) }}</td><td class="hidden text-right tabular-nums md:table-cell">{{ pct(t.action_rate) }}</td><td class="hidden text-right tabular-nums md:table-cell">{{ n(t.empty_count) }}</td></tr>
          </tbody>
        </table></div>
      </section>
    </template>

    <template v-else>
      <section class="card mt-3.5">
        <div class="card-hd"><h2>AI 调用</h2></div>
        <div class="overflow-x-auto"><table class="tbl">
          <thead><tr><th>功能</th><th class="text-right">调用</th><th class="text-right">人数</th><th class="text-right">成功率</th><th class="hidden text-right md:table-cell">平均耗时</th><th class="hidden text-right md:table-cell">Token</th></tr></thead>
          <tbody><tr v-for="f in data.features" :key="f.purpose" class="cursor-pointer hover:bg-subtle" @click="go(f.drill)"><td class="font-medium">{{ f.label }}</td><td class="text-right tabular-nums">{{ f.calls }}</td><td class="text-right tabular-nums">{{ f.users }}</td><td class="text-right tabular-nums" :class="{ 'text-bad': f.success_rate != null && f.success_rate < 0.9 }">{{ pct(f.success_rate) }}</td><td class="hidden text-right tabular-nums md:table-cell">{{ ms(f.avg_latency_ms) }}</td><td class="hidden text-right tabular-nums md:table-cell">{{ n(f.tokens) }}</td></tr></tbody>
        </table></div>
      </section>
      <ul class="m-0 mt-3.5 grid list-none gap-3.5 p-0 sm:grid-cols-3">
        <li v-for="(t, k) in data.tasks" :key="k" class="card cursor-pointer px-[18px] py-3.5" @click="go(t.drill)">
          <p class="m-0 font-semibold">{{ t.label || TASK[k] }}</p>
          <p class="m-0 mt-1 text-2xl font-bold tabular-nums">{{ pct(t.completion_rate) }}<span class="ml-1.5 text-xs font-normal text-mute">完成率</span></p>
          <p class="m-0 mt-1 text-xs text-mute">共 {{ t.total }} 次 · 完成 {{ t.done }} · 失败 {{ t.failed }} · {{ t.users }} 人 · 耗时 {{ secs(t.avg_duration_s) }}</p>
        </li>
      </ul>
    </template>

    <ul v-if="data?.notes?.length" class="m-0 mt-3.5 list-none p-0 text-xs text-mute"><li v-for="x in data.notes" :key="x" class="py-0.5">{{ x }}</li></ul>
  </div>
</template>
