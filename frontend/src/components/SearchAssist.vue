<script setup>
import { ref, watch } from 'vue'
import { api } from '../api'
import { clearSearchHistory, forgetSearch, searchHistory } from '../composables/searchHistory'
import Icon from './Icon.vue'

// v3.3 站内搜索框下拉：没输入时显示「最近搜索」和「大家在搜」，输入时给条目名称联想
const props = defineProps({ q: { type: String, default: '' } })
const emit = defineEmits(['pick', 'open'])
const firstLine = (s) => String(s).split(/\r?\n/)[0] // 历史存完整原文（可能多行），这里只显示第一行

const hot = ref(null)
const sugg = ref([])
let timer
let seq = 0

async function loadHot() {
  try {
    hot.value = await api('/api/search/hot')
  } catch {
    hot.value = []
  }
}
loadHot()

watch(
  () => props.q.trim(),
  (q) => {
    clearTimeout(timer)
    if (!q) return (sugg.value = [])
    timer = setTimeout(async () => {
      const my = ++seq
      try {
        const r = await api(`/api/search/suggest?q=${encodeURIComponent(q)}`)
        if (my === seq) sugg.value = r
      } catch {}
    }, 180)
  },
  { immediate: true },
)

// 联想里高亮命中的部分
function parts(name) {
  const q = props.q.trim()
  const i = q ? name.toLowerCase().indexOf(q.toLowerCase()) : -1
  return i < 0 ? [name, '', ''] : [name.slice(0, i), name.slice(i, i + q.length), name.slice(i + q.length)]
}
</script>

<template>
  <div v-if="q.trim() || searchHistory.length || (hot && hot.length)" class="assist glass-strong absolute inset-x-0 top-full z-40 mt-2 overflow-hidden rounded-[12px] p-2 shadow-[0_22px_48px_-20px_rgb(11_47_122/0.5)]" @mousedown.prevent>
    <!-- 输入中：联想 -->
    <template v-if="q.trim()">
      <ul v-if="sugg.length" class="m-0 list-none p-0" role="listbox" aria-label="搜索联想">
        <li v-for="(s, i) in sugg" :key="s.id" class="assist-row" :style="{ '--d': `${i * 30}ms` }">
          <button class="flex w-full cursor-pointer items-center gap-2.5 rounded-[8px] px-2.5 py-2 text-left transition-colors hover:bg-hover" @click="emit('open', s.id)">
            <Icon name="search" :size="14" class="shrink-0 text-mute" />
            <span class="min-w-0 flex-1">
              <span class="block truncate text-[14px]">{{ parts(s.name)[0] }}<b class="font-semibold text-brand">{{ parts(s.name)[1] }}</b>{{ parts(s.name)[2] }}</span>
              <span v-if="s.summary" class="block truncate text-[12px] text-mute">{{ s.summary }}</span>
            </span>
            <span v-if="s.category" class="shrink-0 rounded-full bg-hover px-2 py-0.5 text-[11px] text-ink-2">{{ s.category }}</span>
          </button>
        </li>
      </ul>
      <p v-else class="m-0 px-2.5 py-2 text-[12.5px] text-mute">按回车用 AI 语义搜索「{{ q.trim() }}」</p>
    </template>

    <!-- 没输入：最近搜索 + 大家在搜 -->
    <template v-else>
      <div v-if="searchHistory.length" class="px-1.5 pt-1 pb-2">
        <div class="mb-1.5 flex items-center"><span class="cap">最近搜索</span><button class="ml-auto cursor-pointer text-[12px] text-mute hover:text-danger" @click="clearSearchHistory">清空</button></div>
        <div class="flex flex-wrap gap-1.5">
          <span v-for="(h, i) in searchHistory" :key="h" class="assist-chip group inline-flex items-center rounded-full border border-line bg-white/80 text-[12.5px] transition-colors hover:border-brand" :style="{ '--d': `${i * 25}ms` }">
            <button class="max-w-[220px] cursor-pointer truncate py-1 pr-1 pl-2.5 hover:text-brand" :title="h" @click="emit('pick', h)">{{ firstLine(h) }}</button>
            <button class="grid h-6 w-6 cursor-pointer place-items-center rounded-full text-mute hover:text-danger" :aria-label="`删除 ${h}`" @click="forgetSearch(h)"><Icon name="x" :size="11" /></button>
          </span>
        </div>
      </div>
      <div v-if="hot && hot.length" class="px-1.5 pt-1 pb-1" :class="{ 'border-t border-line-2 pt-2.5': searchHistory.length }">
        <p class="cap mb-1.5">大家在搜</p>
        <div class="grid grid-cols-2 gap-x-3 gap-y-0.5">
          <button v-for="(h, i) in hot" :key="h.q" class="assist-row flex min-w-0 cursor-pointer items-center gap-2 rounded-[7px] px-1.5 py-1.5 text-left text-[13px] transition-colors hover:bg-hover" :style="{ '--d': `${i * 30}ms` }" @click="emit('pick', h.q)">
            <span class="w-4 shrink-0 text-center font-mono text-[12px] font-semibold" :class="i < 3 ? 'text-brand' : 'text-mute'">{{ i + 1 }}</span>
            <span class="min-w-0 truncate">{{ h.q }}</span>
          </button>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.assist {
  animation: pop 0.28s var(--ease-out-expo);
  transform-origin: 50% 0;
}
.assist-row,
.assist-chip {
  animation: assistin 0.35s var(--ease-out-expo) both;
  animation-delay: var(--d);
}
@keyframes assistin {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
}
@media (prefers-reduced-motion: reduce) {
  .assist,
  .assist-row,
  .assist-chip {
    animation: none;
  }
}
</style>
