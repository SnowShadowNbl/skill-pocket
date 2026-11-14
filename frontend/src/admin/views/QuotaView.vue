<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { api, formatTime } from '../../api'
import Icon from '../../components/Icon.vue'
import { confirmDialog } from '../../composables/dialog'
import { toast } from '../../composables/toast'
import AiLedgerPanel from '../components/AiLedgerPanel.vue'
import AiUsagePanel from '../components/AiUsagePanel.vue'
import ASelect from '../components/ASelect.vue'

// AI 与成本：消耗（功能 / 模型 / 用户 / 天，估算成本）、额度账本、免费额度与每个账号每天的用量
const route = useRoute()
const router = useRouter()
const TABS = [['usage', '消耗'], ['ledger', '额度账本'], ['quota', '额度']]
const tab = computed(() => (TABS.some((t) => t[0] === route.query.tab) ? route.query.tab : 'usage'))
const setTab = (t) => router.replace({ query: { tab: t === 'usage' ? undefined : t } })
const settings = ref(null)
const draft = ref('')
const board = ref(null)
const records = ref(null)
const days = ref(14)
const DAY_OPTIONS = [{ value: 7, label: '最近 7 天' }, { value: 14, label: '最近 14 天' }, { value: 30, label: '最近 30 天' }]

const fmt = (n) => (n == null ? '—' : Number(n).toLocaleString())
const short = (n) => (!n ? '' : Math.abs(n) >= 10000 ? `${(n / 10000).toFixed(Math.abs(n) >= 1e6 ? 0 : 1)}万` : String(n))
const fail = (e) => toast(e.message, 'error')

async function loadSettings() {
  settings.value = await api('/api/admin/quota/settings')
  draft.value = String(settings.value.default_free)
}
async function loadBoard() {
  board.value = null
  board.value = await api(`/api/admin/quota/board?days=${days.value}`)
}
async function loadRecords() {
  records.value = await api('/api/admin/quota/records')
}
onMounted(() => Promise.all([loadSettings(), loadBoard()]).catch(fail))
watch(days, () => loadBoard().catch(fail))

const draftNum = computed(() => Number(String(draft.value).replace(/[,，\s]/g, '')))
const draftOk = computed(() => Number.isInteger(draftNum.value) && draftNum.value >= 0 && settings.value && draftNum.value !== settings.value.default_free)

async function saveDefault(value) {
  const v = value ?? draftNum.value
  if (!(await confirmDialog({ title: `免费额度默认值改为 ${fmt(v)}？`, message: '只影响之后第一次使用 AI 的账号。已经发放过的账号不变，需要的话在用户详情里「重置」。', okText: '保存' }))) return
  try {
    settings.value = await api('/api/admin/quota/settings', { method: 'PUT', body: { default_free: v } })
    draft.value = String(settings.value.default_free)
    toast('已保存', 'success')
  } catch (e) {
    fail(e)
  }
}

// 热力：每个格子的深浅按当天用量相对全表最大值
// 最近的一天放最左边，不用横向滚动就能看到今天
const daysDesc = computed(() => [...(board.value?.days || [])].reverse())
const maxCell = computed(() => Math.max(1, ...(board.value?.users || []).flatMap((u) => Object.values(u.days))))
const cellStyle = (v) => (v ? { background: `rgb(37 99 235 / ${0.12 + 0.75 * (v / maxCell.value)})`, color: v / maxCell.value > 0.55 ? '#fff' : '' } : {})
</script>

<template>
  <div>
    <div class="flex flex-wrap items-center gap-3">
      <h1 class="m-0 text-xl font-semibold">AI 与成本</h1>
      <div class="seg ml-auto"><button v-for="t in TABS" :key="t[0]" :class="{ on: tab === t[0] }" @click="setTab(t[0])">{{ t[1] }}</button></div>
    </div>

    <AiUsagePanel v-if="tab === 'usage'" class="mt-5 block" />
    <AiLedgerPanel v-else-if="tab === 'ledger'" class="mt-5 block" />
    <template v-else>
    <section class="card">
      <div class="card-hd"><h2>免费额度默认值</h2></div>
      <div v-if="!settings" class="card-bd"><div class="skeleton h-24" /></div>
      <div v-else class="card-bd grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)]">
        <form class="flex flex-wrap items-end gap-2" @submit.prevent="saveDefault()">
          <label class="min-w-0 flex-1 text-xs text-mute">新账号第一次使用 AI 时发放
            <input v-model="draft" class="input mt-1" inputmode="numeric" aria-describedby="quota-std" />
          </label>
          <button class="btn btn-primary" :disabled="!draftOk">保存</button>
          <button v-if="settings.default_free !== settings.standard_free" type="button" class="btn" @click="saveDefault(settings.standard_free)">恢复标准值</button>
          <p id="quota-std" class="m-0 w-full text-xs text-mute">当前 {{ fmt(settings.default_free) }}（约等于真实 token {{ short(settings.default_free / settings.rate) }}）；系统标准值 {{ fmt(settings.standard_free) }}</p>
        </form>
        <div class="rounded-lg bg-subtle p-3 text-[13px] leading-relaxed text-ink-2">
          <p class="m-0 font-semibold text-ink">标准值怎么来的</p>
          <p class="mt-1 mb-0">{{ settings.explain }}</p>
          <p class="mt-2 mb-0 text-xs text-mute">不计费的平台 AI：站内搜索、搜索标签、内容审核、昵称审核、反馈分析、地名翻译。</p>
        </div>
      </div>
    </section>

    <section class="card mt-3.5">
      <div class="card-hd flex-wrap gap-2">
        <h2>每个账号每天的用量</h2>
        <ASelect v-model="days" :options="DAY_OPTIONS" label="时间范围" class="ml-auto w-40" />
      </div>
      <div v-if="!board" class="card-bd"><div class="skeleton h-48" /></div>
      <p v-else-if="!board.users.length" class="empty">这段时间还没有账号用过 AI</p>
      <div v-else class="overflow-x-auto">
        <table class="tbl text-[12.5px]">
          <thead>
            <tr>
              <th class="sticky left-0 z-[1] bg-white">账号</th>
              <th class="text-right">余额</th><th class="text-right">合计</th>
              <th v-for="d in daysDesc" :key="d" class="text-center font-normal whitespace-nowrap text-mute">{{ d.slice(5).replace('-', '/') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="u in board.users" :key="u.id">
              <td class="sticky left-0 z-[1] bg-white">
                <RouterLink :to="{ path: '/users', query: { user: u.id } }" class="font-semibold hover:text-primary">{{ u.remark || u.nickname }}</RouterLink>
                <span class="block max-w-[180px] truncate text-xs text-mute">{{ u.remark ? u.nickname + ' · ' : '' }}{{ u.email }}</span>
              </td>
              <td class="text-right tabular-nums" :class="{ 'text-bad': u.balance <= 0 }">{{ fmt(u.balance) }}</td>
              <td class="text-right font-semibold tabular-nums">{{ short(u.total) }}</td>
              <td v-for="d in daysDesc" :key="d" class="px-1 text-center tabular-nums" :style="cellStyle(u.days[d])" :title="u.days[d] ? `${d}：${fmt(u.days[d])}` : ''">{{ short(u.days[d]) }}</td>
            </tr>
            <tr class="font-semibold">
              <td class="sticky left-0 z-[1] bg-white">全部</td><td /><td class="text-right tabular-nums">{{ short(Object.values(board.total).reduce((a, b) => a + b, 0)) }}</td>
              <td v-for="d in daysDesc" :key="d" class="px-1 text-center tabular-nums">{{ short(board.total[d]) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    </template>
  </div>
</template>
