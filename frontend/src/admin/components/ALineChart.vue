<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

// 多折线趋势图：宽度跟随容器，悬停显示当天各项数字，点图例可显示 / 隐藏某一项
//   <ALineChart :data="[{ date: '2026-11-06', register: 3, … }]" :series="[{ key, label, color, dashed? }]" :height="220" />
const props = defineProps({
  data: { type: Array, default: () => [] },
  series: { type: Array, default: () => [] },
  height: { type: Number, default: 220 },
})
const box = ref(null)
const w = ref(600)
const hover = ref(-1)
const off = ref(new Set())
let ro
onMounted(() => {
  if (box.value?.clientWidth) w.value = Math.max(240, box.value.clientWidth)
  ro = new ResizeObserver(([e]) => (w.value = Math.max(240, e.contentRect.width)))
  ro.observe(box.value)
})
onBeforeUnmount(() => ro?.disconnect())

const PAD_B = 22
const shown = computed(() => props.series.filter((s) => !off.value.has(s.key)))
const g = computed(() => {
  const d = props.data
  const h = props.height
  const max = Math.max(4, ...shown.value.flatMap((s) => d.map((r) => r[s.key] || 0))) * 1.15
  const x = (i) => (d.length < 2 ? w.value / 2 : 6 + (i / (d.length - 1)) * (w.value - 12))
  const y = (v) => h - PAD_B - (v / max) * (h - PAD_B - 8)
  const lines = shown.value.map((s) => ({ ...s, points: d.map((r, i) => `${x(i)},${y(r[s.key] || 0)}`).join(' ') }))
  const step = Math.max(1, Math.ceil(d.length / Math.max(2, Math.min(7, Math.floor(w.value / 72)))))
  const labels = d.map((r, i) => ({ i, x: x(i), text: r.date.slice(5).replace('-', '/') }))
    .filter((l) => l.i === d.length - 1 || (l.i % step === 0 && d.length - 1 - l.i >= step * 0.6))
  const grid = [0.25, 0.5, 0.75, 1].map((f) => ({ y: y((max * f) / 1.15), v: Math.round((max * f) / 1.15) }))
  return { x, y, lines, labels, grid, h }
})
function onMove(e) {
  if (!props.data.length) return
  const r = box.value.getBoundingClientRect()
  const i = Math.round(((e.clientX - r.left - 6) / (w.value - 12)) * (props.data.length - 1))
  hover.value = Math.min(props.data.length - 1, Math.max(0, i))
}
function toggle(key) {
  const s = new Set(off.value)
  s.has(key) ? s.delete(key) : s.add(key)
  off.value = s
}
</script>

<template>
  <div>
    <div class="mb-2 flex flex-wrap gap-x-1 gap-y-1">
      <button
        v-for="s in series"
        :key="s.key"
        type="button"
        class="flex h-8 items-center gap-1.5 rounded-md px-2 text-[12.5px] transition-opacity hover:bg-subtle"
        :class="off.has(s.key) ? 'opacity-40' : ''"
        :aria-pressed="!off.has(s.key)"
        @click="toggle(s.key)"
      >
        <span class="h-0.5 w-4 rounded" :style="{ background: s.color }" />{{ s.label }}
      </button>
    </div>
    <div ref="box" class="relative" @mousemove="onMove" @mouseleave="hover = -1">
      <svg :width="w" :height="height" class="block max-w-full">
        <g v-for="l in g.grid" :key="l.y">
          <line x1="0" :x2="w" :y1="l.y" :y2="l.y" stroke="#eef2f7" />
          <text x="2" :y="l.y - 4" font-size="10.5" fill="#a3aec0">{{ l.v }}</text>
        </g>
        <polyline v-for="l in g.lines" :key="l.key" :points="l.points" fill="none" :stroke="l.color" stroke-width="2" stroke-linejoin="round" :stroke-dasharray="l.dashed ? '4 3' : undefined" />
        <text v-for="l in g.labels" :key="l.i" :x="l.x" :y="height - 5" font-size="11" fill="#94a3b8" :text-anchor="l.i === 0 ? 'start' : l.i === data.length - 1 ? 'end' : 'middle'">{{ l.text }}</text>
        <g v-if="hover >= 0">
          <line :x1="g.x(hover)" :x2="g.x(hover)" y1="4" :y2="height - PAD_B" stroke="#cbd5e1" stroke-dasharray="3 3" />
          <circle v-for="l in g.lines" :key="l.key" :cx="g.x(hover)" :cy="g.y(data[hover][l.key] || 0)" r="3.5" fill="#fff" :stroke="l.color" stroke-width="2" />
        </g>
      </svg>
      <div
        v-if="hover >= 0"
        class="pointer-events-none absolute top-1 rounded-md bg-ink px-2.5 py-1.5 text-[12px] leading-5 whitespace-nowrap text-white"
        :style="{ left: `${Math.min(Math.max(g.x(hover) - 60, 0), w - 150)}px` }"
      >
        {{ data[hover].date }}
        <span v-for="l in g.lines" :key="l.key" class="block"><i class="mr-1.5 inline-block h-2 w-2 rounded-full" :style="{ background: l.color }" />{{ l.label }} {{ data[hover][l.key] || 0 }}</span>
      </div>
    </div>
  </div>
</template>
