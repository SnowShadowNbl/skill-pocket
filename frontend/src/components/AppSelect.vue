<script setup>
import { computed, nextTick, onBeforeUnmount, ref } from 'vue'
import Icon from './Icon.vue'

// 主题下拉框（替代原生 <select>）：键盘 ↑↓ / 回车 / Esc，支持分组、搜索（选项多时自动出现）
// options: [{ value, label, group?, hint?, disabled? }]
const model = defineModel({ default: null })
const props = defineProps({
  options: { type: Array, required: true },
  placeholder: { type: String, default: '请选择' },
  label: { type: String, default: '' }, // 无障碍名称
  size: { type: String, default: 'md' }, // md / sm
  searchable: { type: Boolean, default: undefined },
  align: { type: String, default: 'left' },
})

const open = ref(false)
const root = ref(null)
const listEl = ref(null)
const q = ref('')
const active = ref(-1)

const canSearch = computed(() => props.searchable ?? props.options.length > 12)
const current = computed(() => props.options.find((o) => o.value === model.value))
const filtered = computed(() => {
  const k = q.value.trim().toLowerCase()
  return k ? props.options.filter((o) => `${o.label} ${o.group || ''}`.toLowerCase().includes(k)) : props.options
})
const groups = computed(() => {
  const out = []
  filtered.value.forEach((o, i) => {
    const g = o.group || ''
    if (!out.length || out[out.length - 1].name !== g) out.push({ name: g, items: [] })
    out[out.length - 1].items.push({ ...o, idx: i })
  })
  return out
})

async function toggle() {
  open.value = !open.value
  if (!open.value) return
  q.value = ''
  active.value = Math.max(0, filtered.value.findIndex((o) => o.value === model.value))
  await nextTick()
  listEl.value?.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: 'nearest' })
}

function choose(o) {
  if (o.disabled) return
  model.value = o.value
  open.value = false
}

function move(d) {
  const n = filtered.value.length
  if (!n) return
  let i = active.value
  for (let k = 0; k < n; k++) {
    i = (i + d + n) % n
    if (!filtered.value[i].disabled) break
  }
  active.value = i
  nextTick(() => listEl.value?.querySelector(`[data-idx="${i}"]`)?.scrollIntoView({ block: 'nearest' }))
}

function onKey(e) {
  if (!open.value) {
    if (['ArrowDown', 'ArrowUp', 'Enter', ' '].includes(e.key)) {
      e.preventDefault()
      toggle()
    }
    return
  }
  if (e.key === 'ArrowDown') (e.preventDefault(), move(1))
  else if (e.key === 'ArrowUp') (e.preventDefault(), move(-1))
  else if (e.key === 'Enter') {
    e.preventDefault()
    const o = filtered.value[active.value]
    if (o) choose(o)
  } else if (e.key === 'Escape') open.value = false
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
      class="field flex w-full cursor-pointer items-center gap-2 text-left"
      :class="size === 'sm' ? 'h-9 text-[13px] sm:h-9' : 'h-11'"
      :aria-label="label || placeholder"
      aria-haspopup="listbox"
      :aria-expanded="open"
      @click="toggle"
    >
      <span class="min-w-0 flex-1 truncate" :class="current ? '' : 'text-mute'">{{ current ? current.label : placeholder }}</span>
      <Icon name="chevron-down" :size="16" class="shrink-0 text-mute transition-transform duration-300" :class="{ 'rotate-180': open }" />
    </button>

    <Transition name="drop">
      <div
        v-if="open"
        class="glass-strong absolute top-full z-40 mt-1.5 w-full min-w-[12rem] overflow-hidden rounded-2xl p-1 shadow-[0_18px_40px_-14px_rgb(11_47_122/0.5)]"
        :class="align === 'right' ? 'right-0' : 'left-0'"
      >
        <div v-if="canSearch" class="p-1">
          <input v-model="q" class="field h-9 text-[13px] sm:h-9" placeholder="搜索" aria-label="搜索选项" autofocus @input="active = 0" />
        </div>
        <ul ref="listEl" class="max-h-72 overflow-y-auto overscroll-contain" role="listbox" :aria-label="label">
          <template v-for="g in groups" :key="g.name">
            <li v-if="g.name" class="px-3 pt-2 pb-1 text-[11.5px] font-semibold text-mute" role="presentation">{{ g.name }}</li>
            <li
              v-for="o in g.items"
              :key="String(o.value)"
              :data-idx="o.idx"
              role="option"
              :aria-selected="o.value === model"
              :aria-disabled="o.disabled"
              class="flex min-h-9 items-center gap-2 rounded-xl px-3 py-1.5 text-[13.5px] transition-colors"
              :class="[
                o.disabled ? 'cursor-not-allowed text-mute/60' : 'cursor-pointer',
                o.idx === active && !o.disabled ? 'bg-brand-soft text-brand' : o.value === model ? 'text-brand' : 'text-ink-2',
              ]"
              @mouseenter="!o.disabled && (active = o.idx)"
              @click="choose(o)"
            >
              <span class="min-w-0 flex-1 truncate">{{ o.label }}</span>
              <span v-if="o.hint" class="shrink-0 text-xs text-mute tabular-nums">{{ o.hint }}</span>
              <Icon v-if="o.value === model" name="check" :size="14" class="shrink-0" />
            </li>
          </template>
          <li v-if="!filtered.length" class="px-3 py-3 text-center text-[13px] text-mute">没有匹配的选项</li>
        </ul>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.drop-enter-active,
.drop-leave-active {
  transition: opacity 0.18s ease, transform 0.25s cubic-bezier(0.16, 1, 0.3, 1);
  transform-origin: top;
}
.drop-enter-from,
.drop-leave-to {
  opacity: 0;
  transform: translateY(-4px) scale(0.98);
}
</style>
