<script setup>
import Icon from '../Icon.vue'

// v3.3.96 GitHub 列的工作流（与小程序一致）：按真实阶段点亮节点，只用 transform / opacity
// ① 理解需求：节点呼吸，拆出的关键词逐个弹出成标签 → ② 搜索：连接线流光，当前那组关键词高亮、搜完打勾 → ③ 排序 → ④ 排除本站
// 全部完成后收成一行小字（summary）
defineProps({
  nodes: { type: Array, required: true },
  active: { type: Number, default: 0 },
  keywords: { type: Array, default: () => [] },
  group: { type: Number, default: 0 },
  summary: { type: String, default: '' },
  failed: { type: String, default: '' },
})
</script>

<template>
  <div class="ghf">
    <p v-if="summary" class="ghf-sum m-0 flex items-start gap-1.5 text-[12.5px] leading-[18px] text-mute">
      <Icon name="check" :size="13" class="mt-[2px] shrink-0 text-ok" /><span class="min-w-0">{{ summary }}</span>
    </p>
    <template v-else>
      <div class="flex items-center">
        <template v-for="(n, i) in nodes" :key="n">
          <div class="ghf-node flex shrink-0 flex-col items-center gap-1" :class="i < active ? 'is-done' : i === active ? 'is-on' : ''">
            <span class="ghf-dot grid h-5 w-5 place-items-center rounded-full">
              <Icon v-if="i < active" name="check" :size="11" :stroke="3" />
              <span v-else class="h-1.5 w-1.5 rounded-full bg-current" />
            </span>
            <span class="text-[11px] leading-3 whitespace-nowrap">{{ n }}</span>
          </div>
          <div v-if="i < nodes.length - 1" class="ghf-line relative mx-1 mb-4 h-[2px] min-w-0 flex-1 overflow-hidden rounded-full" :class="i < active ? 'is-done' : i === active ? 'is-on' : ''">
            <span v-if="i === active" class="ghf-flow absolute inset-y-0 left-0 w-1/2 rounded-full" />
          </div>
        </template>
      </div>
      <div v-if="keywords.length" class="mt-2.5 flex flex-wrap gap-1">
        <span
          v-for="(k, i) in keywords"
          :key="k"
          class="ghf-kw inline-flex max-w-full items-center gap-0.5 rounded-full px-2 py-0.5 text-[11.5px]"
          :class="group > i + 1 ? 'is-done' : group === i + 1 ? 'is-on' : ''"
          :style="{ animationDelay: `${i * 90}ms` }"
        >
          <Icon v-if="group > i + 1" name="check" :size="10" :stroke="3" />
          <span class="truncate">{{ k }}</span>
        </span>
      </div>
      <p v-if="failed" class="mt-1.5 mb-0 text-[12.5px] text-danger">{{ failed }}</p>
    </template>
  </div>
</template>

<style scoped>
.ghf-node { color: var(--color-mute); transition: color 0.3s; }
.ghf-dot { background: var(--color-hover); color: var(--color-mute); transition: background-color 0.3s, color 0.3s, transform 0.4s var(--ease-spring); }
.ghf-node.is-on { color: var(--color-brand); }
.ghf-node.is-on .ghf-dot { background: var(--color-brand-soft); color: var(--color-brand); animation: ghfbreath 1.4s ease-in-out infinite; }
.ghf-node.is-done { color: var(--color-ink-2); }
.ghf-node.is-done .ghf-dot { background: var(--color-brand); color: #fff; }
.ghf-line { background: var(--color-line); }
.ghf-line.is-done { background: var(--color-brand); }
.ghf-flow { background: linear-gradient(90deg, transparent, var(--color-brand), transparent); animation: ghfflow 1.1s linear infinite; }
.ghf-kw { background: #fff; border: 1px solid var(--color-line); color: var(--color-ink-2); animation: ghfpop 0.45s var(--ease-spring) backwards; transition: background-color 0.3s, color 0.3s, border-color 0.3s; }
.ghf-kw.is-on { border-color: var(--color-brand); color: var(--color-brand); background: var(--color-brand-soft); }
.ghf-kw.is-done { color: var(--color-ok); border-color: rgb(22 163 74 / 0.25); }
.ghf-sum { animation: ghfin 0.4s var(--ease-out-expo) backwards; }
@keyframes ghfbreath { 50% { transform: scale(1.18); } }
@keyframes ghfflow { from { transform: translateX(-100%); } to { transform: translateX(200%); } }
@keyframes ghfpop { from { opacity: 0; transform: scale(0.6) translateY(4px); } }
@keyframes ghfin { from { opacity: 0; transform: translateY(-4px); } }
@media (prefers-reduced-motion: reduce) {
  .ghf-flow, .ghf-node.is-on .ghf-dot, .ghf-kw, .ghf-sum { animation: none; }
}
</style>
