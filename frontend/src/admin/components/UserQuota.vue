<script setup>
import { computed, ref, watch } from 'vue'
import { api, formatTime } from '../../api'
import Icon from '../../components/Icon.vue'
import { confirmDialog } from '../../composables/dialog'
import { toast } from '../../composables/toast'
import ASelect from './ASelect.vue'

// 用户详情里的「AI 额度」（v2.6）：余额、充值 / 调整 / 设为 / 重置，每天用量与剩余额度曲线，按用途拆分，全部变动记录
const props = defineProps({ userId: { type: Number, required: true }, name: { type: String, default: '' } })
const emit = defineEmits(['changed'])
const q = ref(null)
const busy = ref(false)
const form = ref({ action: 'recharge', amount: '', yuan: '', note: '' })
const ACTIONS = [
  { value: 'recharge', label: '充值（加额度，记下收款）' },
  { value: 'adjust', label: '调整（加或减，可填负数）' },
  { value: 'set', label: '设为指定额度' },
  { value: 'reset', label: '重置为默认免费额度' },
]

async function load() {
  q.value = null
  q.value = await api(`/api/admin/users/${props.userId}/quota`)
}
watch(() => props.userId, load, { immediate: true })

const fmt = (n) => (n == null ? '—' : Number(n).toLocaleString())
const short = (n) => (Math.abs(n) >= 10000 ? `${(n / 10000).toFixed(Math.abs(n) >= 1e6 ? 0 : 1)}万` : String(n))
const amountNum = computed(() => Number(String(form.value.amount).replace(/[,，\s]/g, '')))
const canSubmit = computed(() => {
  const a = form.value.action
  if (a === 'reset') return true
  if (!Number.isFinite(amountNum.value) || form.value.amount === '') return false
  if (a === 'recharge') return amountNum.value > 0
  if (a === 'adjust') return amountNum.value !== 0
  return amountNum.value >= 0
})

async function submit() {
  const a = form.value.action
  const label = ACTIONS.find((x) => x.value === a).label.split('（')[0]
  const msg = a === 'reset' ? '余额会被设为当前的默认免费额度。' : a === 'set' ? `余额会被设为 ${fmt(amountNum.value)}。` : `余额 ${amountNum.value >= 0 ? '+' : ''}${fmt(amountNum.value)}。`
  if (!(await confirmDialog({ title: `${label}「${props.name}」的 AI 额度？`, message: msg, okText: label }))) return
  busy.value = true
  try {
    q.value = await api(`/api/admin/users/${props.userId}/quota`, {
      method: 'POST',
      body: { action: a, amount: a === 'reset' ? 0 : amountNum.value, yuan: a === 'recharge' && form.value.yuan !== '' ? Number(form.value.yuan) : null, note: form.value.note.trim() },
    })
    toast(`已${label}，当前余额 ${fmt(q.value.balance)}`, 'success')
    form.value = { action: a, amount: '', yuan: '', note: '' }
    emit('changed', q.value.balance)
  } catch (e) {
    toast(e.message, 'error')
  } finally {
    busy.value = false
  }
}

// 近 30 天（固定 30 格）：柱子是每天扣掉的额度，折线是每天结束时的剩余额度
const chart = computed(() => {
  if (!q.value) return null
  const used = new Map(q.value.daily.map((d) => [d.day, d.used]))
  const balMap = new Map(q.value.balance_history.map((d) => [d.day, d.balance]))
  const today = new Date(`${(q.value.balance_history.at(-1)?.day) || new Date().toISOString().slice(0, 10)}T00:00:00`)
  const days = Array.from({ length: 30 }, (_, i) => {
    const d = new Date(today)
    d.setDate(d.getDate() - (29 - i))
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  })
  if (!days.some((d) => used.get(d) || balMap.has(d))) return null
  const W = 540, H = 120, B = 18
  const maxU = Math.max(1, ...days.map((d) => used.get(d) || 0))
  const bals = days.filter((d) => balMap.has(d)).map((d) => balMap.get(d))
  const maxB = Math.max(1, ...bals), minB = Math.min(0, ...bals)
  const bw = W / days.length
  const yB = (v) => 6 + (1 - (v - minB) / (maxB - minB || 1)) * (H - B - 12)
  const pts = days.map((d, i) => (balMap.has(d) ? `${(i + 0.5) * bw},${yB(balMap.get(d))}` : null)).filter(Boolean)
  return {
    W, H, B, bw,
    bars: days.map((d, i) => { const u = used.get(d) || 0; const h = (u / maxU) * (H - B - 10); return { x: i * bw + 1, y: H - B - h, h, w: Math.max(1, bw - 2), d, u } }),
    // 只有一天时画一小段横线，看得出余额在哪
    line: pts.length === 1 ? `${Number(pts[0].split(',')[0]) - bw},${pts[0].split(',')[1]} ${pts[0]}` : pts.join(' '),
    first: days[0].slice(5), last: days[days.length - 1].slice(5), maxU, maxB,
  }
})
</script>

<template>
  <section>
    <h3 class="mt-5 mb-2 text-[13px] font-semibold">AI 额度</h3>
    <div v-if="!q" class="skeleton h-40" />
    <template v-else>
      <div class="grid grid-cols-3 gap-2 text-center">
        <div class="rounded-lg bg-subtle py-2"><b class="block text-lg tabular-nums" :class="{ 'text-bad': q.balance <= 0 }">{{ fmt(q.balance) }}</b><span class="text-xs text-mute">剩余额度</span></div>
        <div class="rounded-lg bg-subtle py-2"><b class="block text-lg tabular-nums">{{ fmt(q.used_today) }}</b><span class="text-xs text-mute">今天用量</span></div>
        <div class="rounded-lg bg-subtle py-2"><b class="block text-lg tabular-nums">{{ fmt(q.used_30d) }}</b><span class="text-xs text-mute">近 30 天</span></div>
      </div>
      <p class="mt-2 text-xs text-mute">
        额度 = 真实 token × {{ q.rate }}。累计发放 {{ fmt(q.granted_total) }}<template v-if="q.recharged_yuan">，累计收款 ¥{{ q.recharged_yuan }}</template>。
        <span v-if="q.unlimited" class="text-ok">管理员账号不受余额限制。</span>
      </p>

      <form class="mt-3 grid gap-2 rounded-lg bg-subtle p-3 sm:grid-cols-2" @submit.prevent="submit">
        <ASelect v-model="form.action" :options="ACTIONS" label="操作" class="sm:col-span-2" />
        <template v-if="form.action !== 'reset'">
          <label class="text-xs text-mute">{{ form.action === 'set' ? '设为（额度）' : form.action === 'adjust' ? '加减额度（负数为扣减）' : '充值额度' }}
            <input v-model="form.amount" class="input mt-1" inputmode="numeric" placeholder="例如 1000000" />
          </label>
          <label v-if="form.action === 'recharge'" class="text-xs text-mute">收款金额（元，可不填）
            <input v-model="form.yuan" class="input mt-1" inputmode="decimal" placeholder="例如 10" />
          </label>
        </template>
        <label class="text-xs text-mute sm:col-span-2">备注（可选，用户能在额度记录里看到）
          <input v-model="form.note" class="input mt-1" maxlength="200" placeholder="例如 微信转账 / 活动赠送" />
        </label>
        <div class="flex items-center gap-2 sm:col-span-2">
          <span v-if="form.action !== 'reset' && form.amount && Number.isFinite(amountNum)" class="text-xs text-mute">约等于真实 token {{ short(Math.round(amountNum / q.rate)) }}</span>
          <button class="btn btn-primary ml-auto" :disabled="!canSubmit || busy"><Icon :name="busy ? 'refresh' : 'check'" :size="14" :class="{ 'animate-spin': busy }" />确定</button>
        </div>
      </form>

      <div v-if="chart" class="mt-4">
        <p class="m-0 flex items-center gap-3 text-xs text-mute">
          <span class="inline-flex items-center gap-1"><span class="h-2.5 w-2.5 rounded-sm bg-primary/60" />每天用量（最高 {{ short(chart.maxU) }}）</span>
          <span class="inline-flex items-center gap-1"><span class="h-0.5 w-3 bg-bad" />剩余额度（最高 {{ short(chart.maxB) }}）</span>
        </p>
        <svg :viewBox="`0 0 ${chart.W} ${chart.H}`" class="mt-1 block w-full" role="img" aria-label="每天用量与剩余额度">
          <rect v-for="b in chart.bars" :key="b.d" :x="b.x" :y="b.y" :width="b.w" :height="Math.max(0, b.h)" class="fill-primary/60"><title>{{ b.d }}：用 {{ fmt(b.u) }}</title></rect>
          <polyline :points="chart.line" fill="none" class="stroke-bad" stroke-width="1.6" stroke-linejoin="round" />
          <text x="0" :y="chart.H - 4" class="fill-mute text-[10px]">{{ chart.first }}</text>
          <text :x="chart.W" :y="chart.H - 4" text-anchor="end" class="fill-mute text-[10px]">{{ chart.last }}</text>
        </svg>
      </div>

      <template v-if="q.by_purpose.length">
        <p class="mt-4 mb-1 text-xs text-mute">近 60 天按用途</p>
        <ul class="m-0 list-none p-0 text-[13px]">
          <li v-for="p in q.by_purpose" :key="p.purpose" class="flex items-center gap-2 border-b border-dashed border-line py-1.5 last:border-0">
            <span>{{ p.label }}</span><span v-if="!p.billed" class="tag tag-gray">不计费</span>
            <span class="ml-auto text-xs text-mute tabular-nums">{{ p.calls }} 次 · {{ short(p.tokens) }} token<template v-if="p.billed"> · 扣 {{ short(p.used) }}</template></span>
          </li>
        </ul>
      </template>

      <template v-if="q.daily.length">
        <p class="mt-4 mb-1 text-xs text-mute">每天明细</p>
        <div class="max-h-56 overflow-y-auto">
          <table class="tbl">
            <thead><tr><th>日期</th><th class="text-right">次数</th><th class="text-right">真实 token</th><th class="text-right">扣额度</th><th class="text-right">当天剩余</th></tr></thead>
            <tbody>
              <tr v-for="d in q.daily" :key="d.day"><td>{{ d.day }}</td><td class="text-right tabular-nums">{{ d.calls }}</td><td class="text-right tabular-nums">{{ fmt(d.tokens) }}</td>
                <td class="text-right tabular-nums">{{ fmt(d.used) }}</td><td class="text-right tabular-nums" :class="{ 'text-bad': d.balance_end <= 0 }">{{ fmt(d.balance_end) }}</td></tr>
            </tbody>
          </table>
        </div>
      </template>

      <p class="mt-4 mb-1 text-xs text-mute">额度变动记录（充值 / 调整 / 重置 / 发放）</p>
      <ul class="m-0 list-none p-0 text-[13px]">
        <li v-for="r in q.ledger" :key="r.id" class="flex flex-wrap items-center gap-x-2 border-b border-dashed border-line py-1.5 last:border-0">
          <span class="tag" :class="r.kind === 'recharge' ? 'tag-ok' : r.kind === 'grant' ? 'tag-blue' : 'tag-gray'">{{ r.kind_label }}</span>
          <b class="tabular-nums" :class="r.delta >= 0 ? 'text-ok' : 'text-bad'">{{ r.delta >= 0 ? '+' : '' }}{{ fmt(r.delta) }}</b>
          <span v-if="r.amount_yuan" class="text-ink-2">¥{{ r.amount_yuan }}</span>
          <span class="min-w-0 truncate text-mute">{{ r.note }}</span>
          <span class="ml-auto text-xs text-mute">余额 {{ fmt(r.balance_after) }} · {{ r.operator || '系统' }} · {{ formatTime(r.created_at) }}</span>
        </li>
      </ul>
    </template>
  </section>
</template>
