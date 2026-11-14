<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api } from '../../api'
import Icon from '../../components/Icon.vue'

// 日期区间选择器（管理端）：点一下选某一天，再点另一天选成区间；每天下面的小数字是当天的条目数。
// v-model 是 { from: 'YYYY-MM-DD' | '', to: 'YYYY-MM-DD' | '' }；field 决定按收录还是修改日期统计
const props = defineProps({
  modelValue: { type: Object, default: () => ({ from: '', to: '' }) },
  field: { type: String, default: 'collected' },
  counts: { type: Boolean, default: true }, // 在每天下面显示当天的条目数（只有条目相关的页面需要）
  placeholder: { type: String, default: '全部日期' },
})
const emit = defineEmits(['update:modelValue'])
const open = ref(false)
const box = ref(null)

const pad = (n) => String(n).padStart(2, '0')
const iso = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
const today = () => iso(new Date())
const shift = (s, n) => {
  const d = new Date(`${s}T00:00:00`)
  d.setDate(d.getDate() + n)
  return iso(d)
}

const view = ref(new Date())
const counts = ref({})
const anchor = ref('') // 点了第一天、等第二天
const monthKey = computed(() => `${view.value.getFullYear()}-${pad(view.value.getMonth() + 1)}`)

async function loadCounts() {
  if (!props.counts) return
  try {
    counts.value = await api(`/api/admin/items/days?month=${monthKey.value}&field=${props.field}`)
  } catch {
    counts.value = {}
  }
}
watch([monthKey, () => props.field, open], () => open.value && loadCounts())

const cells = computed(() => {
  const y = view.value.getFullYear()
  const m = view.value.getMonth()
  const first = new Date(y, m, 1)
  const lead = (first.getDay() + 6) % 7 // 周一开头
  const days = new Date(y, m + 1, 0).getDate()
  const out = Array.from({ length: lead }, () => null)
  for (let d = 1; d <= days; d++) out.push(iso(new Date(y, m, d)))
  return out
})

const from = computed(() => props.modelValue.from)
const to = computed(() => props.modelValue.to)
const inRange = (d) => from.value && to.value && d >= from.value && d <= to.value
const label = computed(() => {
  if (!from.value) return props.placeholder
  if (from.value === to.value) return from.value
  return `${from.value} ~ ${to.value}`
})

function pick(d) {
  if (!anchor.value) {
    anchor.value = d
    emit('update:modelValue', { from: d, to: d })
  } else {
    const [a, b] = [anchor.value, d].sort()
    anchor.value = ''
    emit('update:modelValue', { from: a, to: b })
    open.value = false
  }
}
function preset(kind) {
  const t = today()
  const map = {
    today: [t, t],
    yesterday: [shift(t, -1), shift(t, -1)],
    week: [shift(t, -6), t],
    month: [shift(t, -29), t],
    all: ['', ''],
  }
  const [a, b] = map[kind]
  anchor.value = ''
  emit('update:modelValue', { from: a, to: b })
  open.value = false
}
function move(n) {
  const d = new Date(view.value)
  d.setMonth(d.getMonth() + n, 1)
  view.value = d
}

function onDoc(e) {
  if (open.value && box.value && !box.value.contains(e.target)) {
    open.value = false
    anchor.value = ''
  }
}
onMounted(() => document.addEventListener('pointerdown', onDoc))
onBeforeUnmount(() => document.removeEventListener('pointerdown', onDoc))
watch(open, (v) => v && from.value && (view.value = new Date(`${from.value}T00:00:00`)))
</script>

<template>
  <div ref="box" class="relative">
    <button type="button" class="input flex items-center gap-2 text-left" :class="{ 'border-primary': open }" :aria-expanded="open" @click="open = !open">
      <Icon name="clock" :size="15" class="shrink-0 text-mute" />
      <span class="min-w-0 flex-1 truncate" :class="from ? 'text-ink' : 'text-mute'">{{ label }}</span>
      <span v-if="from" class="grid h-5 w-5 place-items-center rounded text-mute hover:bg-subtle hover:text-ink" role="button" aria-label="清除日期" @click.stop="preset('all')"><Icon name="x" :size="13" /></span>
    </button>
    <Transition name="fade">
      <div v-if="open" class="absolute top-full left-0 z-40 mt-1.5 w-[300px] rounded-lg border border-line bg-white p-3 shadow-[0_12px_32px_-12px_rgba(14,26,43,.25)]">
        <div class="flex flex-wrap gap-1.5">
          <button v-for="p in [['today', '今天'], ['yesterday', '昨天'], ['week', '近 7 天'], ['month', '近 30 天'], ['all', '全部']]" :key="p[0]" type="button" class="btn btn-sm" @click="preset(p[0])">{{ p[1] }}</button>
        </div>
        <div class="mt-3 flex items-center">
          <button type="button" class="btn btn-sm h-7 w-7 px-0" aria-label="上个月" @click="move(-1)"><Icon name="chevron-left" :size="14" /></button>
          <b class="flex-1 text-center text-[13px] font-semibold">{{ view.getFullYear() }} 年 {{ view.getMonth() + 1 }} 月</b>
          <button type="button" class="btn btn-sm h-7 w-7 px-0" aria-label="下个月" @click="move(1)"><Icon name="chevron-right" :size="14" /></button>
        </div>
        <div class="mt-2 grid grid-cols-7 text-center text-[11px] text-mute"><span v-for="w in '一二三四五六日'" :key="w">{{ w }}</span></div>
        <div class="mt-1 grid grid-cols-7 gap-0.5">
          <template v-for="(d, i) in cells" :key="i">
            <span v-if="!d" />
            <button
              v-else
              type="button"
              class="day relative flex h-9 flex-col items-center justify-center rounded-md text-[12.5px] tabular-nums transition-colors"
              :class="[
                d === from || d === to ? 'bg-primary font-semibold text-white' : inRange(d) ? 'bg-primary-soft text-primary' : 'hover:bg-subtle',
                d > today() ? 'text-mute/50' : '',
                d === today() && d !== from && d !== to ? 'ring-1 ring-primary/40' : '',
              ]"
              :disabled="d > today()"
              :title="counts[d] ? `${d}：${counts[d]} 个条目` : d"
              @click="pick(d)"
            >
              {{ Number(d.slice(8)) }}
              <span v-if="counts[d]" class="font-mono text-[9px] leading-none" :class="d === from || d === to ? 'text-white/85' : 'text-primary'">{{ counts[d] }}</span>
            </button>
          </template>
        </div>
        <p class="mt-2 mb-0 text-[11.5px] text-mute">{{ anchor ? '再点一天，选成一段时间' : '点一天看当天；点两天选一段时间' }}</p>
      </div>
    </Transition>
  </div>
</template>
