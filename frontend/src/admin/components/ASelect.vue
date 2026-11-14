<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import Icon from '../../components/Icon.vue'

// 管理端下拉框（不用原生 select）：键盘上下选择、回车确认、Esc 关闭；可分组（option.group）、可搜索
const props = defineProps({
  modelValue: { type: [String, Number], default: '' },
  options: { type: Array, default: () => [] }, // [{ value, label, group? }]
  label: { type: String, default: '' },
  searchable: Boolean,
})
const emit = defineEmits(['update:modelValue'])
const open = ref(false)
const active = ref(0)
const root = ref(null)
const list = ref(null)
const search = ref(null)
const q = ref('')
const current = computed(() => props.options.find((o) => o.value === props.modelValue) || props.options[0])
const shown = computed(() => {
  const k = q.value.trim().toLowerCase()
  return k ? props.options.filter((o) => `${o.label} ${o.group || ''}`.toLowerCase().includes(k)) : props.options
})

function toggle() {
  open.value = !open.value
  if (open.value) {
    q.value = ''
    active.value = Math.max(0, props.options.indexOf(current.value))
    nextTick(() => {
      list.value?.querySelector('[data-active]')?.scrollIntoView({ block: 'nearest' })
      search.value?.focus()
    })
  }
}
function pick(o) {
  emit('update:modelValue', o.value)
  open.value = false
}
function onKey(e) {
  if (!open.value && ['ArrowDown', 'Enter', ' '].includes(e.key)) return (e.preventDefault(), toggle())
  if (!open.value) return
  if (e.key === 'Escape') open.value = false
  else if (e.key === 'ArrowDown') active.value = Math.min(shown.value.length - 1, active.value + 1)
  else if (e.key === 'ArrowUp') active.value = Math.max(0, active.value - 1)
  else if (e.key === 'Enter') shown.value[active.value] && pick(shown.value[active.value])
  else return
  e.preventDefault()
  nextTick(() => list.value?.querySelector('[data-active]')?.scrollIntoView({ block: 'nearest' }))
}
watch(q, () => (active.value = 0))
const outside = (e) => root.value && !root.value.contains(e.target) && (open.value = false)
document.addEventListener('pointerdown', outside)
onBeforeUnmount(() => document.removeEventListener('pointerdown', outside))
</script>

<template>
  <div ref="root" class="relative">
    <button
      type="button"
      class="input flex items-center gap-2 text-left"
      :class="{ '!border-primary shadow-[0_0_0_3px_rgb(31_111_235/.12)]': open }"
      :aria-label="label"
      aria-haspopup="listbox"
      :aria-expanded="open"
      @click="toggle"
      @keydown="onKey"
    >
      <span class="min-w-0 flex-1 truncate">{{ current?.label }}</span>
      <Icon name="chevron-down" :size="15" class="text-mute transition-transform" :class="{ 'rotate-180': open }" />
    </button>
    <Transition name="fade">
      <div v-if="open" class="absolute top-full right-0 left-0 z-30 mt-1 min-w-48 rounded-lg border border-line bg-white p-1 shadow-[0_8px_24px_-8px_rgba(15,29,51,.2)]">
        <input v-if="searchable" ref="search" v-model="q" class="input mb-1 h-8 text-[13px]" placeholder="搜索…" aria-label="搜索选项" @keydown="onKey" />
        <ul ref="list" class="m-0 max-h-72 list-none overflow-y-auto p-0" role="listbox">
          <template v-for="(o, i) in shown" :key="String(o.value)">
            <li v-if="o.group && o.group !== shown[i - 1]?.group" class="px-2.5 pt-2 pb-1 text-[11.5px] text-mute" role="presentation">{{ o.group }}</li>
            <li
              role="option"
              :aria-selected="o.value === modelValue"
              :data-active="i === active || undefined"
              class="flex h-8 cursor-pointer items-center gap-2 rounded-md px-2.5 text-[13px]"
              :class="[i === active ? 'bg-[#f1f5fb]' : '', o.value === modelValue ? 'font-semibold text-primary' : '', o.group ? 'pl-4' : '']"
              @mouseenter="active = i"
              @click="pick(o)"
            >
              <span class="flex-1 truncate">{{ o.label }}</span><Icon v-if="o.value === modelValue" name="check" :size="14" />
            </li>
          </template>
          <li v-if="!shown.length" class="px-2.5 py-2 text-[13px] text-mute">没有匹配的选项</li>
        </ul>
      </div>
    </Transition>
  </div>
</template>
