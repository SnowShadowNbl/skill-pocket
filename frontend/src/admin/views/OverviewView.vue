<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { api, isCancelled, timeAgo } from '../../api'
import Icon from '../../components/Icon.vue'
import { promptDialog } from '../../composables/dialog'
import { toast } from '../../composables/toast'
import TrendChart from '../components/TrendChart.vue'

// 概览：今天的关键数字、访问趋势与地区，以及需要处理的审核和反馈、实时动态
const props = defineProps({ summary: { type: Object, default: () => ({}) } })
const emit = defineEmits(['changed'])

const days = ref(30)
const ov = ref(null)
const reviews = ref(null)
const feed = ref(null)
const feedback = ref(null)
const deciding = ref(0)

// 待处理：各类等你处理的数量，点进对应页面；还没拿到数据时显示「—」
const todos = computed(() => {
  const s = props.summary
  const n = (v) => (v == null ? null : v)
  return [
    { label: '条目待审', n: n(s.pending_reviews), to: '/reviews' },
    { label: '评论待审', n: n(s.pending_comments), to: '/comments' },
    { label: '采集待确认', n: n(s.pending_crawl), to: '/crawl-review' },
    { label: '新反馈', n: n(s.feedback_new), to: '/feedback', urgent: s.feedback_urgent },
    ...(s.pending?.ingest_stuck != null || s.pending?.ingest_failed != null ? [{ label: '收录任务卡住 / 失败', n: (s.pending.ingest_stuck || 0) + (s.pending.ingest_failed || 0), to: '/ingest-tasks', urgent: s.pending.ingest_stuck }] : []),
    ...(s.pending?.alerts != null ? [{ label: '运行告警', n: s.pending.alerts.open, to: '/resources?tab=alerts', urgent: s.pending.alerts.critical }] : []),
    ...(s.pending?.takedowns != null ? [{ label: '下架申请', n: s.pending.takedowns, to: '/takedowns' }] : []),
  ]
})

const today = new Intl.DateTimeFormat('zh-CN', { dateStyle: 'full' }).format(new Date())
const maxRegion = computed(() => Math.max(1, ...(ov.value?.regions || []).map((r) => r.count)))
const kpis = computed(() => {
  const t = ov.value?.today || {}
  const s = ov.value?.series || []
  const y = s.at(-2) || {}
  const delta = (a, b) => (b ? ` · ${a >= b ? '+' : ''}${Math.round(((a - b) / b) * 100)}%` : '')
  return [
    { label: '当前在线', value: t.online, note: '5 分钟内活跃', live: true },
    { label: '今日访客', value: t.uv, note: y.uv != null ? `昨日 ${y.uv}${delta(t.uv, y.uv)}` : '' },
    { label: '今日浏览', value: t.pv, note: y.pv != null ? `昨日 ${y.pv}${delta(t.pv, y.pv)}` : '' },
    { label: '今日新访客', value: t.new, note: `近 ${days.value} 天游客转注册 ${ov.value?.range.conversions ?? 0}` },
  ]
})

async function loadOverview() {
  ov.value = await api(`/api/admin/analytics/overview?days=${days.value}`)
}
async function loadLists() {
  const [r, f, fb] = await Promise.all([
    api('/api/admin/reviews/pending'),
    api('/api/admin/feed?limit=8'),
    api('/api/admin/feedback?status=new'),
  ])
  reviews.value = r.filter((x) => x.review_state === 'admin').concat(r.filter((x) => x.review_state !== 'admin'))
  feed.value = f.items
  feedback.value = fb
}
async function load() {
  try {
    await Promise.all([loadOverview(), loadLists()])
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  }
}

async function decide(it, decision) {
  let reason = ''
  if (decision === 'reject') {
    reason = await promptDialog({ title: `拒绝「${it.name}」`, message: '写一句原因，提交人会在「我提交的」里看到。', placeholder: '例如：与 AI 无关 / 重复收录', okText: '拒绝', required: true })
    if (!reason) return
  }
  deciding.value = it.id
  try {
    await api(`/api/admin/items/${it.id}/review`, { method: 'POST', body: { decision, reason } })
    toast(decision === 'approve' ? `「${it.name}」已上线` : `已拒绝「${it.name}」`, 'success')
    reviews.value = reviews.value.filter((x) => x.id !== it.id)
    emit('changed')
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  } finally {
    deciding.value = 0
  }
}

function aiTag(it) {
  const o = it.ai_opinion
  if (it.review_state !== 'admin') return ['AI 审核中', 'tag-blue']
  if (!o) return ['待人工', 'tag-gray']
  const pct = o.confidence != null ? ` ${Math.round(o.confidence * 100)}%` : ''
  if (o.decision === 'approve') return [`建议通过${pct}`, 'tag-ok']
  if (o.decision === 'reject') return [`建议拒绝${pct}`, 'tag-bad']
  return [`拿不准${pct}`, 'tag-warn']
}

const PRIORITY = { P0: 'tag-bad', P1: 'tag-bad', P2: 'tag-warn', P3: 'tag-gray', P4: 'tag-gray' }

watch(days, loadOverview)
const timer = setInterval(() => !document.hidden && load(), 30000)
onBeforeUnmount(() => clearInterval(timer))
onMounted(load)
</script>

<template>
  <div>
    <RouterLink v-if="summary.resource_alerts" to="/resources" class="mb-4 flex items-center gap-2 rounded-lg border border-bad/30 bg-bad-soft px-3.5 py-2.5 text-[13.5px] font-medium text-bad hover:underline">
      <Icon name="alert" :size="16" />有 {{ summary.resource_alerts }} 项资源需要处理（如 DeepSeek 余额不足、磁盘快满），点这里查看
    </RouterLink>
    <h1 class="m-0 text-xl font-semibold">概览</h1>
    <p class="mt-1 mb-5 text-[13px] text-mute">{{ today }} · 每 30 秒自动刷新</p>

    <div class="mb-3.5 grid grid-cols-2 gap-3.5 md:grid-cols-3 xl:grid-cols-5">
      <RouterLink v-for="t in todos" :key="t.label" :to="t.to" class="card flex min-h-14 items-center gap-3 px-[18px] py-3 text-ink no-underline transition-colors hover:border-primary">
        <b class="text-2xl tabular-nums" :class="t.n == null ? 'text-mute' : t.n ? (t.urgent ? 'text-bad' : 'text-primary') : 'text-mute'">{{ t.n ?? '—' }}</b>
        <span class="text-[13px] text-ink-2">{{ t.label }}<span v-if="t.urgent" class="ml-1.5 tag tag-bad">{{ t.urgent }} 条紧急</span></span>
      </RouterLink>
    </div>

    <div class="grid grid-cols-2 gap-3.5 md:grid-cols-4">
      <div v-for="k in kpis" :key="k.label" class="card px-[18px] py-4">
        <p class="m-0 flex items-center text-[13px] text-mute">
          <span v-if="k.live" class="mr-1.5 inline-block h-2 w-2 rounded-full bg-ok shadow-[0_0_0_3px_#dcfce7]" />{{ k.label }}
        </p>
        <b v-if="ov" class="mt-1.5 mb-0.5 block text-[28px] font-bold tracking-tight tabular-nums">{{ (k.value ?? 0).toLocaleString() }}</b>
        <span v-else class="skeleton my-2.5 block h-7 w-16" />
        <span class="text-xs text-mute">{{ k.note }}</span>
      </div>
    </div>

    <div class="mt-3.5 grid gap-3.5 xl:grid-cols-[1.7fr_1fr]">
      <section class="card">
        <div class="card-hd">
          <h2>访问趋势</h2>
          <span class="hidden items-center gap-1.5 text-xs text-ink-2 sm:flex"><i class="inline-block h-[3px] w-3.5 rounded bg-primary" />浏览</span>
          <span class="hidden items-center gap-1.5 text-xs text-ink-2 sm:flex"><i class="inline-block h-[3px] w-3.5 rounded bg-[#5aa2ff]" />访客</span>
          <div class="seg ml-auto">
            <button v-for="d in [7, 30, 90]" :key="d" :class="{ on: days === d }" @click="days = d">{{ d }} 天</button>
          </div>
        </div>
        <div class="card-bd">
          <TrendChart v-if="ov" :series="ov.series" />
          <div v-else class="skeleton h-[230px]" />
          <p v-if="ov" class="mt-2 mb-0 text-[13px] text-ink-2">
            近 {{ ov.days }} 天：访客 <b>{{ ov.range.visitors }}</b>，其中登录用户 <b>{{ ov.range.logged_in }}</b>，行为 <b>{{ ov.range.events }}</b> 次
          </p>
        </div>
      </section>
      <section class="card">
        <div class="card-hd"><h2>访客地区</h2><RouterLink to="/visitors" class="ml-auto text-xs text-mute hover:text-primary">近 {{ days }} 天 · 查看访客</RouterLink></div>
        <div class="card-bd">
          <p v-if="ov && !ov.regions.length" class="empty">暂无数据</p>
          <div v-for="r in ov?.regions || []" :key="r.name" class="grid grid-cols-[84px_1fr_44px] items-center gap-2.5 py-[5px] text-[13px]">
            <span class="truncate">{{ r.name }}</span>
            <span class="h-2 overflow-hidden rounded bg-[#eef2f8]"><i class="block h-full rounded bg-primary" :style="{ width: `${(r.count / maxRegion) * 100}%` }" /></span>
            <em class="text-right text-ink-2 not-italic tabular-nums">{{ r.count }}</em>
          </div>
        </div>
      </section>
    </div>

    <div class="mt-3.5 grid gap-3.5 xl:grid-cols-[1.7fr_1fr]">
      <section class="card">
        <div class="card-hd">
          <h2>待审核</h2>
          <span v-if="reviews?.length" class="tag tag-bad">{{ reviews.length }}</span>
          <RouterLink to="/reviews" class="btn btn-sm ml-auto">审核设置与日志</RouterLink>
        </div>
        <div v-if="!reviews" class="card-bd"><div class="skeleton h-28" /></div>
        <p v-else-if="!reviews.length" class="empty">没有待审核的提交</p>
        <div v-else class="overflow-x-auto">
          <table class="tbl">
            <thead><tr><th>条目</th><th>AI 意见</th><th class="hidden md:table-cell">提交人</th><th /></tr></thead>
            <tbody>
              <tr v-for="it in reviews" :key="it.id">
                <td class="max-w-[320px]">
                  <a :href="`/items/${it.id}`" target="_blank" class="font-semibold hover:text-primary">{{ it.name }}</a>
                  <span class="block truncate text-xs text-mute">{{ it.repo_full_name ? it.repo_full_name + (it.sub_path ? '/' + it.sub_path : '') : it.github_url }}<template v-if="it.kind?.name || it.category?.name"> · {{ it.kind?.name || it.category?.name }}</template></span>
                  <span v-if="it.ai_opinion?.reason" class="mt-0.5 block text-xs text-ink-2">AI：{{ it.ai_opinion.reason }}</span>
                </td>
                <td><span class="tag" :class="aiTag(it)[1]">{{ aiTag(it)[0] }}</span></td>
                <td class="hidden md:table-cell">{{ it.submitter?.nickname || '—' }}<span class="block text-xs text-mute">{{ timeAgo(it.collected_at) }}</span></td>
                <td class="text-right whitespace-nowrap">
                  <template v-if="it.review_state === 'admin'">
                    <button class="btn btn-sm btn-danger" :disabled="deciding === it.id" @click="decide(it, 'reject')">拒绝</button>
                    <button class="btn btn-sm btn-primary ml-1.5" :disabled="deciding === it.id" @click="decide(it, 'approve')">通过</button>
                  </template>
                  <span v-else class="text-xs text-mute">等待 AI</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
      <section class="card">
        <div class="card-hd"><h2>实时动态</h2><span class="tag tag-ok">● 实时</span><RouterLink to="/activity" class="ml-auto text-xs text-mute hover:text-primary">全部</RouterLink></div>
        <div v-if="!feed" class="card-bd"><div class="skeleton h-40" /></div>
        <p v-else-if="!feed.length" class="empty">还没有用户动态</p>
        <ul v-else class="m-0 list-none p-0">
          <li v-for="f in feed" :key="f.id" class="grid grid-cols-[64px_1fr] gap-2.5 border-b border-line px-[18px] py-2.5 text-[13px] last:border-0">
            <time class="pt-px text-xs text-mute">{{ timeAgo(f.created_at) }}</time>
            <div class="min-w-0">
              <p class="m-0 break-words"><b>{{ f.user?.nickname || (f.actor === 'system' ? '系统' : '游客') }}</b> <span class="text-ink-2">{{ f.action_label }}</span> {{ f.summary }}</p>
              <span v-if="f.ip" class="mt-0.5 flex items-center gap-1 text-xs text-mute">
                <Icon name="eye" :size="12" />{{ f.geo || '未知地区' }} · {{ f.ip }}
              </span>
            </div>
          </li>
        </ul>
      </section>
    </div>

    <section class="card mt-3.5">
      <div class="card-hd">
        <h2>新反馈</h2>
        <span v-if="feedback?.total" class="tag tag-blue">{{ feedback.total }}</span>
        <RouterLink to="/feedback" class="ml-auto text-xs text-mute hover:text-primary">全部反馈</RouterLink>
      </div>
      <div v-if="!feedback" class="card-bd"><div class="skeleton h-20" /></div>
      <p v-else-if="!feedback.items.length" class="empty">没有未处理的新反馈</p>
      <table v-else class="tbl">
        <tbody>
          <tr v-for="fb in feedback.items.slice(0, 5)" :key="fb.id" class="cursor-pointer" @click="$router.push({ path: '/feedback', query: { id: fb.id } })">
            <td class="w-14"><span class="tag" :class="PRIORITY[fb.priority] || 'tag-gray'">{{ fb.priority || '待分析' }}</span></td>
            <td>
              {{ fb.ai_analysis?.summary || fb.content.slice(0, 60) }}
              <span v-if="fb.ai_analysis?.cause" class="block text-xs text-mute">AI：{{ fb.ai_analysis.cause.slice(0, 80) }}</span>
            </td>
            <td class="hidden w-24 md:table-cell"><span class="tag tag-gray">{{ fb.category_label }}</span></td>
            <td class="w-28 text-right text-xs text-mute">{{ timeAgo(fb.created_at) }}</td>
          </tr>
        </tbody>
      </table>
    </section>
  </div>
</template>
