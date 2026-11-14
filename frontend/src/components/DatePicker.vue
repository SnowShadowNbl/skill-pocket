<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import Icon from './Icon.vue'

// 主题日历选择器：只有 available 里的日期可选，其余置灰；月份可切换，键盘 ← → ↑ ↓ 在可选日期间移动
// value / available 都是 'YYYY-MM-DD' 字符串
const model = defineModel({ type: String, default: '' })
const props = defineProps({
  available: { type: Array, default: () => [] },
  label: { type: String, default: '选择日期' },
  emptyText: { type: String, default: '暂无数据' },
})

const open = ref(false)
const root = ref(null)
const view = ref(monthOf(model.value || props.available[0] || today()))
const WEEK = ['一', '二', '三', '四', '五', '六', '日']

function today() {
  const d = new Date()
  return fmt(d.getFullYear(), d.getMonth() + 1, d.getDate())
}
function fmt(y, m, d) {
  return `${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`
}
function monthOf(s) {
  const [y, m] = s.split('-').map(Number)
  return { y, m }
}

const avail = computed(() => new Set(props.available))
const sorted = computed(() => [...props.available].sort())
const minMonth = computed(() => (sorted.value.length ? monthOf(sorted.value[0]) : null))
const maxMonth = computed(() => (sorted.value.length ? monthOf(sorted.value[sorted.value.length - 1]) : null))
const key = (v) => v.y * 12 + v.m
const canPrev = computed(() => minMonth.value && key(view.value) > key(minMonth.value))
const canNext = computed(() => maxMonth.value && key(view.value) < key(maxMonth.value))

const cells = computed(() => {
  const { y, m } = view.value
  const first = new Date(y, m - 1, 1)
  const lead = (first.getDay() + 6) % 7 // 周一为第一列
  const days = new Date(y, m, 0).getDate()
  const out = Array.from({ length: lead }, () => null)
  for (let d = 1; d <= days; d++) {
    const s = fmt(y, m, d)
    out.push({ d, s, on: avail.value.has(s), today: s === today() })
  }
  return out
})
const monthCount = computed(() => cells.value.filter((c) => c?.on).length)

const display = computed(() => {
  if (!model.value) return props.label
  const [y, m, d] = model.value.split('-').map(Number)
  const w = WEEK[(new Date(y, m - 1, d).getDay() + 6) % 7]
  return `${y} 年 ${m} 月 ${d} 日 · 周${w}`
})
// v3.2 手机上工具栏挤成一行：日期改短显示（11/7 周六）
const short = computed(() => {
  if (!model.value) return props.label
  const [y, m, d] = model.value.split("-").map(Number)
  return `${m}/${d} 周${WEEK[(new Date(y, m - 1, d).getDay() + 6) % 7]}`
})

watch(model, (v) => v && (view.value = monthOf(v)))
watch(
  () => props.available,
  (a) => !model.value && a.length && (view.value = monthOf(a[0])),
)

function shift(n) {
  let { y, m } = view.value
  m += n
  if (m < 1) (m = 12), y--
  if (m > 12) (m = 1), y++
  view.value = { y, m }
}

function pick(c) {
  if (!c?.on) return
  model.value = c.s
  open.value = false
}

function step(dir) {
  // 在可选日期之间移动（跨月也可以）
  const i = sorted.value.indexOf(model.value)
  const next = sorted.value[i + dir]
  if (next) model.value = next
}

function onKey(e) {
  if (!open.value) return
  if (e.key === 'Escape') open.value = false
  else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') (e.preventDefault(), step(-1))
  else if (e.key === 'ArrowRight' || e.key === 'ArrowDown') (e.preventDefault(), step(1))
  else if (e.key === 'Enter') (e.preventDefault(), (open.value = false))
}

function onDoc(e) {
  if (open.value && root.value && !root.value.contains(e.target)) open.value = false
}
addEventListener('pointerdown', onDoc, true)
onBeforeUnmount(() => removeEventListener('pointerdown', onDoc, true))
</script>

<template>
  <div ref="root" class="relative" @keydown="onKey">
    <button
      type="button"
      class="glass flex h-10 cursor-pointer items-center gap-1.5 rounded-xl px-2.5 text-[13px] whitespace-nowrap sm:gap-2 sm:px-3 sm:text-[13.5px] transition-all duration-300 hover:bg-white/85"
      :class="open ? 'ring-2 ring-brand/40' : ''"
      :aria-label="label"
      :aria-expanded="open"
      aria-haspopup="dialog"
      :disabled="!available.length"
      @click="open = !open"
    >
      <Icon name="clock" :size="15" class="text-brand" />
      <span class="hidden font-medium tabular-nums sm:inline">{{ available.length ? display : emptyText }}</span>
      <span class="font-medium tabular-nums sm:hidden">{{ available.length ? short : emptyText }}</span>
      <Icon name="chevron-down" :size="15" class="text-mute transition-transform duration-300" :class="{ 'rotate-180': open }" />
    </button>

    <Transition name="drop">
      <div
        v-if="open"
        class="glass-strong absolute top-full right-0 z-40 mt-2 w-[296px] rounded-[12px] p-3.5 shadow-[0_22px_48px_-18px_rgb(11_47_122/0.55)]"
        role="dialog"
        :aria-label="label"
      >
        <div class="flex items-center gap-1">
          <button type="button" class="nav-btn" :disabled="!canPrev" aria-label="上个月" @click="shift(-1)"><Icon name="chevron-right" :size="16" class="rotate-180" /></button>
          <p class="flex-1 text-center text-[15px] font-bold tabular-nums">{{ view.y }} 年 {{ view.m }} 月</p>
          <button type="button" class="nav-btn" :disabled="!canNext" aria-label="下个月" @click="shift(1)"><Icon name="chevron-right" :size="16" /></button>
        </div>

        <div class="mt-3 grid grid-cols-7 gap-1 text-center text-[11.5px] text-mute">
          <span v-for="w in WEEK" :key="w" class="py-1">{{ w }}</span>
        </div>
        <div class="grid grid-cols-7 gap-1">
          <template v-for="(c, i) in cells" :key="i">
            <span v-if="!c" />
            <button
              v-else
              type="button"
              class="day relative grid h-9 place-items-center rounded-xl text-[13.5px] tabular-nums transition-all duration-200"
              :class="[
                c.s === model ? 'bg-brand font-bold text-white shadow-[0_6px_14px_-6px_rgb(30_86_214/0.8)]' : '',
                c.on && c.s !== model ? 'cursor-pointer font-semibold text-ink hover:bg-brand-soft hover:text-brand' : '',
                !c.on ? 'cursor-not-allowed text-ink/25' : '',
              ]"
              :disabled="!c.on"
              :aria-pressed="c.s === model"
              :aria-label="`${c.s}${c.on ? '' : '（无数据）'}`"
              @click="pick(c)"
            >
              {{ c.d }}
              <span v-if="c.on && c.s !== model" class="absolute bottom-1 h-1 w-1 rounded-full bg-brand/60" />
              <span v-if="c.today && c.s !== model" class="absolute inset-0 rounded-xl ring-1 ring-brand/30" />
            </button>
          </template>
        </div>

        <div class="mt-3 flex items-center justify-between border-t border-line pt-2.5 text-[12px] text-mute">
          <span class="flex items-center gap-1.5"><span class="h-1.5 w-1.5 rounded-full bg-brand/60" />本月 {{ monthCount }} 天有数据</span>
          <button
            v-if="sorted.length"
            type="button"
            class="cursor-pointer font-medium text-brand hover:underline"
            @click="(model = sorted[sorted.length - 1]), (open = false)"
          >最新一期</button>
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.nav-btn {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  border-radius: 10px;
  color: var(--color-ink-2);
  cursor: pointer;
  transition: background-color 0.2s, opacity 0.2s;
}
.nav-btn:hover:not(:disabled) {
  background: rgb(255 255 255 / 0.85);
}
.nav-btn:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}
.drop-enter-active,
.drop-leave-active {
  transition: opacity 0.2s ease, transform 0.3s cubic-bezier(0.16, 1, 0.3, 1);
  transform-origin: top right;
}
.drop-enter-from,
.drop-leave-to {
  opacity: 0;
  transform: translateY(-6px) scale(0.97);
}
</style>
