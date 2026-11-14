<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

// 访问趋势：浏览（实线 + 面积）与访客（虚线）。宽度跟随容器，悬停显示当天数字
const props = defineProps({ series: { type: Array, default: () => [] }, height: { type: Number, default: 230 } })
const box = ref(null)
const w = ref(600)
const hover = ref(-1)
let ro

onMounted(() => {
  ro = new ResizeObserver(([e]) => (w.value = Math.max(240, e.contentRect.width)))
  ro.observe(box.value)
})
onBeforeUnmount(() => ro?.disconnect())

const PAD_B = 22
const g = computed(() => {
  const s = props.series
  const h = props.height
  const max = Math.max(4, ...s.map((d) => Math.max(d.pv, d.uv))) * 1.15
  const x = (i) => (s.length < 2 ? w.value / 2 : 6 + (i / (s.length - 1)) * (w.value - 12))
  const y = (v) => h - PAD_B - (v / max) * (h - PAD_B - 8)
  const pv = s.map((d, i) => `${x(i)},${y(d.pv)}`).join(' ')
  const uv = s.map((d, i) => `${x(i)},${y(d.uv)}`).join(' ')
  const step = Math.max(1, Math.ceil(s.length / Math.max(2, Math.min(7, Math.floor(w.value / 72)))))
  const labels = s.map((d, i) => ({ i, x: x(i), text: d.day.slice(5).replace('-', '/') }))
    // 最后一天总显示；离它太近的刻度去掉，避免文字重叠
    .filter((l) => l.i === s.length - 1 || (l.i % step === 0 && s.length - 1 - l.i >= step * 0.6))
  const grid = [0.25, 0.5, 0.75, 1].map((f) => ({ y: y(max * f / 1.15), v: Math.round((max * f) / 1.15) }))
  return { x, y, pv, uv, labels, grid, h, area: s.length ? `${x(0)},${h - PAD_B} ${pv} ${x(s.length - 1)},${h - PAD_B}` : '' }
})

function onMove(e) {
  const s = props.series
  if (!s.length) return
  const r = box.value.getBoundingClientRect()
  const i = Math.round(((e.clientX - r.left - 6) / (w.value - 12)) * (s.length - 1))
  hover.value = Math.min(s.length - 1, Math.max(0, i))
}
</script>

<template>
  <div ref="box" class="relative" @mousemove="onMove" @mouseleave="hover = -1">
    <svg :width="w" :height="height" class="block">
      <g v-for="l in g.grid" :key="l.y">
        <line x1="0" :x2="w" :y1="l.y" :y2="l.y" stroke="#eef2f7" />
        <text x="2" :y="l.y - 4" font-size="10.5" fill="#a3aec0">{{ l.v }}</text>
      </g>
      <polygon :points="g.area" fill="rgb(30 86 214 / .08)" />
      <polyline :points="g.pv" fill="none" stroke="#1e56d6" stroke-width="2" stroke-linejoin="round" />
      <polyline :points="g.uv" fill="none" stroke="#5aa2ff" stroke-width="2" stroke-dasharray="4 3" stroke-linejoin="round" />
      <text v-for="l in g.labels" :key="l.i" :x="l.x" :y="height - 5" font-size="11" fill="#94a3b8"
        :text-anchor="l.i === 0 ? 'start' : l.i === series.length - 1 ? 'end' : 'middle'">{{ l.text }}</text>
      <g v-if="hover >= 0">
        <line :x1="g.x(hover)" :x2="g.x(hover)" y1="4" :y2="height - PAD_B" stroke="#cbd5e1" stroke-dasharray="3 3" />
        <circle :cx="g.x(hover)" :cy="g.y(series[hover].pv)" r="4" fill="#fff" stroke="#1e56d6" stroke-width="2" />
        <circle :cx="g.x(hover)" :cy="g.y(series[hover].uv)" r="3.5" fill="#fff" stroke="#5aa2ff" stroke-width="2" />
      </g>
    </svg>
    <div
      v-if="hover >= 0"
      class="pointer-events-none absolute top-1 rounded-md bg-ink px-2.5 py-1.5 text-[12px] whitespace-nowrap text-white"
      :style="{ left: `${Math.min(Math.max(g.x(hover) - 60, 0), w - 150)}px` }"
    >
      {{ series[hover].day }}<br />浏览 {{ series[hover].pv }} · 访客 {{ series[hover].uv }} · 新访客 {{ series[hover].new }}
    </div>
  </div>
</template>
