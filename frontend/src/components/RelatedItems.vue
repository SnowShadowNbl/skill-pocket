<script setup>
import { ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { api, formatStars } from '../api'
import { compareState, COMPARE_MAX, fromItem, inCompare, startCompare } from '../composables/compare'
import { useItemLink } from '../composables/itemLink'
import { toast } from '../composables/toast'
import CompareToggle from './CompareToggle.vue'
import Icon from './Icon.vue'

// 详情页推荐：「收藏了这条的人还收藏了」+「同类推荐」，横向滑动的小卡片。
// v3.3.6：鼠标放上去可以用滚轮横向滑动、两端有翻页按钮；每张卡片都能勾选「对比」，同类推荐可以一键和当前条目一起 AI 对比
const props = defineProps({ item: { type: Object, required: true } })
const itemLink = useItemLink()
const data = ref(null)
const rows = ref({})
const edge = ref({})

watch(
  () => props.item.id,
  async (id) => {
    data.value = null
    try {
      data.value = await api(`/api/items/${id}/related`)
    } catch {
      data.value = { similar: [], also: [] }
    }
  },
  { immediate: true },
)

function updateEdge(key) {
  const el = rows.value[key]
  if (el) edge.value = { ...edge.value, [key]: { start: el.scrollLeft <= 2, end: el.scrollLeft >= el.scrollWidth - el.clientWidth - 2 } }
}
// 竖向滚轮转成横向滑动；滑到头之后不拦截，页面照常上下滚
function onWheel(e, key) {
  const el = e.currentTarget
  if (Math.abs(e.deltaX) > Math.abs(e.deltaY)) return
  const max = el.scrollWidth - el.clientWidth
  if (max <= 0) return
  if ((e.deltaY < 0 && el.scrollLeft <= 0) || (e.deltaY > 0 && el.scrollLeft >= max - 1)) return
  e.preventDefault()
  el.scrollLeft += e.deltaY
  updateEdge(key)
}
function page(key, dir) {
  const el = rows.value[key]
  if (el) el.scrollBy({ left: dir * el.clientWidth * 0.8, behavior: 'smooth' })
}

// 一键对比：当前条目 + 你勾选的同类（没勾就取前 3 个），直接开始 AI 对比
const starting = ref(false)
async function compareWithSimilar() {
  const picked = data.value.similar.filter((it) => inCompare(fromItem(it)))
  const others = (picked.length ? picked : data.value.similar.slice(0, 3)).slice(0, COMPARE_MAX - 1)
  compareState.list = [fromItem(props.item), ...others.map(fromItem)]
  starting.value = true
  try {
    if (await startCompare()) toast(`已开始对比 ${others.length + 1} 个，进度在右下角`, 'success', 3000)
  } catch (e) {
    toast(e.message, 'error')
  } finally {
    starting.value = false
  }
}
</script>

<template>
  <div v-if="!data" class="mt-7 flex gap-2.5 overflow-hidden"><div v-for="n in 3" :key="n" class="skeleton-bar h-[148px] w-[176px] shrink-0 rounded-[12px]" /></div>
  <div v-else>
    <section v-for="g in [['also', '收藏了这条的人还收藏了', 'heart'], ['similar', '同类推荐', 'layers']]" v-show="data[g[0]].length" :key="g[0]" v-reveal class="rel-sec mt-7" :aria-label="g[1]">
      <div class="flex flex-wrap items-center gap-2">
        <h3 class="section-title flex items-center gap-1.5"><Icon :name="g[2]" :size="16" class="text-brand" />{{ g[1] }}</h3>
        <button
          v-if="g[0] === 'similar' && item.status === 'published'"
          class="btn-primary btn-sm ml-auto"
          :disabled="starting || compareState.starting"
          @click="compareWithSimilar"
        ><Icon name="sparkles" :size="14" :class="{ 'animate-pulse': starting }" />{{ starting ? '开始对比…' : '和它们一起 AI 对比' }}</button>
      </div>
      <div class="relative mt-3">
        <div
          :ref="(el) => (rows[g[0]] = el)"
          class="scrollbar-none -mx-5 flex snap-x gap-2.5 overflow-x-auto scroll-smooth px-5 pb-1 md:-mx-8 md:px-8"
          @wheel="onWheel($event, g[0])"
          @scroll.passive="updateEdge(g[0])"
        >
          <div v-for="(it, i) in data[g[0]]" :key="it.id" class="rel-card relative w-[176px] shrink-0 snap-start" :style="{ '--d': `${i * 50}ms` }">
            <RouterLink :to="itemLink(it.id)" class="group flex h-full flex-col overflow-hidden rounded-[12px] border border-line bg-white/80">
              <span class="relative block aspect-[16/9] overflow-hidden bg-brand-soft">
                <img v-if="it.cover_url" :src="it.cover_url" alt="" loading="lazy" class="h-full w-full object-cover transition-transform duration-700 ease-out-expo group-hover:scale-[1.06]" />
                <span v-if="g[0] === 'also' && it.co_count > 1" class="absolute bottom-1.5 left-1.5 rounded-full bg-white/90 px-1.5 text-[10.5px] font-medium text-brand">{{ it.co_count }} 人同收</span>
              </span>
              <span class="flex min-h-0 flex-1 flex-col p-2.5">
                <b class="truncate text-[13px] font-semibold group-hover:text-brand">{{ it.name }}</b>
                <span class="mt-0.5 line-clamp-2 text-[11.5px] leading-[16px] text-ink-2">{{ it.summary }}</span>
                <span v-if="it.stars != null" class="mt-auto pt-1.5 font-mono text-[10.5px] text-mute">★ {{ formatStars(it.stars) }}</span>
              </span>
            </RouterLink>
            <CompareToggle :entry="fromItem(it)" small class="absolute top-1.5 right-1.5 z-[2]" />
          </div>
        </div>
        <!-- 桌面端两端翻页按钮 -->
        <button v-show="!(edge[g[0]]?.start ?? true)" class="rel-nav left-0 max-md:hidden" aria-label="向左" @click="page(g[0], -1)"><Icon name="chevron-left" :size="16" /></button>
        <button v-show="!(edge[g[0]]?.end ?? data[g[0]].length <= 4)" class="rel-nav right-0 max-md:hidden" aria-label="向右" @click="page(g[0], 1)"><Icon name="chevron-right" :size="16" /></button>
      </div>
    </section>
  </div>
</template>

<style scoped>
.rel-card {
  animation: relin 0.5s var(--ease-out-expo) both;
  animation-delay: var(--d);
}
.rel-card > a {
  transition: transform 0.35s var(--ease-out-expo), border-color 0.3s, box-shadow 0.4s var(--ease-out-expo);
}
@media (hover: hover) and (pointer: fine) {
  .rel-card:hover > a {
    transform: translateY(-3px);
    border-color: #b9cbea;
    box-shadow: 0 16px 28px -20px rgb(11 47 122 / 0.6);
  }
}
.rel-card > a:active {
  transform: scale(0.98);
}
.rel-nav {
  position: absolute;
  top: 38%;
  z-index: 3;
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  margin: 0 -10px;
  border-radius: 999px;
  background: #fff;
  color: var(--color-brand);
  border: 1px solid var(--color-line);
  box-shadow: 0 8px 18px -10px rgb(11 47 122 / 0.6);
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.3s, transform 0.3s var(--ease-spring);
}
.rel-sec:hover .rel-nav {
  opacity: 1;
}
.rel-nav:hover {
  transform: scale(1.08);
}
@keyframes relin {
  from {
    opacity: 0;
    transform: translateX(14px);
  }
}
@media (prefers-reduced-motion: reduce) {
  .rel-card {
    animation: none;
  }
}
</style>
