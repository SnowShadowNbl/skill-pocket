<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import Icon from '../../components/Icon.vue'
import ASelect from './ASelect.vue'

// 日期 + 时间选择（北京时间，半小时一档），不用原生控件。v-model 是 'YYYY-MM-DD HH:mm' 或空字符串
//   <ADateTime v-model="startsAt" placeholder="不限" />
const props = defineProps({ modelValue: { type: String, default: '' }, placeholder: { type: String, default: '不限' }, min: { type: String, default: '' } })
const emit = defineEmits(['update:modelValue'])
const open = ref(false)
const box = ref(null)
const pad = (n) => String(n).padStart(2, '0')
const iso = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`

const view = ref(new Date())
const day = ref('')
const time = ref('09:00')
const timeOptions = Array.from({ length: 48 }, (_, i) => {
  const t = `${pad(Math.floor(i / 2))}:${i % 2 ? '30' : '00'}`
  return { value: t, label: t }
})

function sync() {
  const [d, t] = props.modelValue ? props.modelValue.split(' ') : ['', '09:00']
  day.value = d
  time.value = timeOptions.some((o) => o.value === t) ? t : t ? `${t.slice(0, 2)}:${Number(t.slice(3)) >= 30 ? '30' : '00'}` : '09:00'
  view.value = d ? new Date(`${d}T00:00:00`) : new Date()
}
watch(() => props.modelValue, sync, { immediate: true })

const monthLabel = computed(() => `${view.value.getFullYear()} 年 ${view.value.getMonth() + 1} 月`)
const cells = computed(() => {
  const y = view.value.getFullYear()
  const m = view.value.getMonth()
  const lead = (new Date(y, m, 1).getDay() + 6) % 7
  const days = new Date(y, m + 1, 0).getDate()
  return [...Array.from({ length: lead }, () => null), ...Array.from({ length: days }, (_, i) => iso(new Date(y, m, i + 1)))]
})
const today = iso(new Date())
const move = (n) => {
  const d = new Date(view.value)
  d.setMonth(d.getMonth() + n, 1)
  view.value = d
}
function commit() {
  if (day.value) emit('update:modelValue', `${day.value} ${time.value}`)
}
function pick(d) {
  day.value = d
  commit()
}
function setTime(t) {
  time.value = t
  commit()
}
function clear() {
  emit('update:modelValue', '')
  open.value = false
}
const outside = (e) => box.value && !box.value.contains(e.target) && (open.value = false)
onMounted(() => document.addEventListener('pointerdown', outside))
onBeforeUnmount(() => document.removeEventListener('pointerdown', outside))
</script>

<template>
  <div ref="box" class="relative">
    <button type="button" class="input flex items-center gap-2 text-left" :class="{ '!border-primary': open }" :aria-expanded="open" @click="open = !open">
      <Icon name="clock" :size="15" class="shrink-0 text-mute" />
      <span class="min-w-0 flex-1 truncate tabular-nums" :class="modelValue ? 'text-ink' : 'text-mute'">{{ modelValue || placeholder }}</span>
      <span v-if="modelValue" class="grid h-5 w-5 place-items-center rounded text-mute hover:bg-subtle hover:text-ink" role="button" aria-label="清除" @click.stop="clear"><Icon name="x" :size="13" /></span>
    </button>
    <Transition name="fade">
      <div v-if="open" class="absolute top-full left-0 z-50 mt-1.5 w-[300px] max-w-[calc(100vw-32px)] rounded-lg border border-line bg-white p-3 shadow-[0_12px_32px_-12px_rgba(14,26,43,.25)]">
        <div class="flex items-center">
          <button type="button" class="btn btn-sm h-7 w-7 px-0" aria-label="上个月" @click="move(-1)"><Icon name="chevron-left" :size="14" /></button>
          <b class="flex-1 text-center text-[13px] font-semibold">{{ monthLabel }}</b>
          <button type="button" class="btn btn-sm h-7 w-7 px-0" aria-label="下个月" @click="move(1)"><Icon name="chevron-right" :size="14" /></button>
        </div>
        <div class="mt-2 grid grid-cols-7 text-center text-[11px] text-mute"><span v-for="w in '一二三四五六日'" :key="w">{{ w }}</span></div>
        <div class="mt-1 grid grid-cols-7 gap-0.5">
          <template v-for="(d, i) in cells" :key="i">
            <span v-if="!d" />
            <button
              v-else
              type="button"
              class="h-9 rounded-md text-[12.5px] tabular-nums transition-colors"
              :class="[d === day ? 'bg-primary font-semibold text-white' : 'hover:bg-subtle', d === today && d !== day ? 'ring-1 ring-primary/40' : '', min && d < min.slice(0, 10) ? 'text-mute/40' : '']"
              :disabled="!!min && d < min.slice(0, 10)"
              @click="pick(d)"
            >{{ Number(d.slice(8)) }}</button>
          </template>
        </div>
        <div class="mt-3 flex items-center gap-2">
          <div class="min-w-0 flex-1"><ASelect :model-value="time" :options="timeOptions" label="时间" @update:model-value="setTime" /></div>
          <button type="button" class="btn" @click="open = false">完成</button>
        </div>
      </div>
    </Transition>
  </div>
</template>
