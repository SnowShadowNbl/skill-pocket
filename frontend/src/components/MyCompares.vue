<script setup>
import { onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { api, timeAgo } from '../api'
import AiTag from './AiTag.vue'
import Icon from './Icon.vue'

// 「口袋 → 我的 AI 对比」（v3.2 改为卡片）：缩略图由参与对比的条目封面拼成，中间一枚 VS；
// 悬停时拼图展开、VS 转一下，按下轻微下沉，和条目卡片的手感一致
const list = ref(null)
const error = ref('')

onMounted(async () => {
  try {
    list.value = await api('/api/me/compares')
  } catch (e) {
    error.value = e.message
  }
})

// 没有封面的（外站仓库）用名称首字母配一块渐变色
const TINTS = ['from-brand to-brand-2', 'from-sky to-brand', 'from-brand-2 to-sky', 'from-[#5b7cfa] to-[#1e56d6]']
const initial = (s) => (s || '?').replace(/^[^a-zA-Z0-9一-龥]+/, '').slice(0, 1).toUpperCase()

</script>

<template>
  <div>
    <p v-if="error" class="panel px-6 py-8 text-center text-sm text-danger">{{ error }}</p>
    <div v-else-if="!list" class="grid grid-cols-2 gap-2.5 sm:gap-3.5 lg:grid-cols-3">
      <div v-for="n in 6" :key="n" class="overflow-hidden rounded-lg border border-line bg-panel">
        <div class="skeleton-bar aspect-[16/9.5]" />
        <div class="space-y-2 p-3"><div class="skeleton-bar h-3 w-3/5 rounded" /><div class="skeleton-bar h-3 rounded" /></div>
      </div>
    </div>
    <div v-else-if="!list.length" class="panel flex flex-col items-center gap-3 px-6 py-12 text-center text-sm text-ink-2">
      <span class="float-y grid h-12 w-12 place-items-center rounded-2xl bg-brand-soft text-brand"><Icon name="layers" :size="22" /></span>
      <p class="font-medium text-ink">还没有做过 AI 对比</p>
      <p class="text-[12.5px] text-mute">勾选卡片上的「对比」，在底部对比栏点「开始对比」</p>
    </div>

    <div v-else class="grid grid-cols-2 gap-2.5 sm:gap-3.5 lg:grid-cols-3">
      <RouterLink
        v-for="(r, i) in list"
        :key="r.id"
        v-reveal="i % 6"
        :to="`/compare/${r.id}`"
        v-tilt
        class="icard cmp-card group relative flex flex-col overflow-hidden rounded-lg border border-line bg-panel"
      >
        <!-- 缩略图：封面拼图 + VS -->
        <div class="relative aspect-[16/9.5] overflow-hidden bg-brand-soft">
          <div class="cmp-mosaic absolute inset-0 grid gap-[2px]" :class="(r.covers || []).length > 2 ? 'grid-cols-2 grid-rows-2' : 'grid-cols-2'">
            <div
              v-for="(c, k) in (r.covers && r.covers.length ? r.covers : r.names).slice(0, 4)"
              :key="k"
              class="cmp-tile relative overflow-hidden"
              :class="{ 'row-span-2': k === 0 && (r.covers || r.names).length === 3 }"
              :style="{ '--d': `${k * 60}ms` }"
            >
              <img v-if="r.covers && r.covers[k]" :src="r.covers[k]" alt="" loading="lazy" class="cv-img h-full w-full object-cover" />
              <div v-else class="grid h-full w-full place-items-center bg-gradient-to-br text-xl font-bold text-white/90" :class="TINTS[k % TINTS.length]">{{ initial(r.names[k]) }}</div>
            </div>
          </div>
          <div class="pointer-events-none absolute inset-0 bg-[linear-gradient(180deg,transparent_45%,rgb(11_47_122/0.35))]" />
          <span class="cmp-vs absolute top-1/2 left-1/2 grid h-9 w-9 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full bg-white font-mono text-[11px] font-extrabold text-brand shadow-[0_8px_18px_-8px_rgb(11_47_122/0.7)]">VS</span>
          <span class="absolute right-2 bottom-2 rounded-full bg-black/35 px-2 py-0.5 font-mono text-[10.5px] text-white backdrop-blur">{{ r.names.length }} 个</span>
          <span v-if="r.status === 'running'" class="absolute top-2 left-2 inline-flex items-center gap-1 rounded-full bg-white/90 px-2 py-0.5 text-[11px] text-brand"><Icon name="refresh" :size="11" class="animate-spin" />对比中</span>
          <span v-else-if="r.status === 'failed'" class="absolute top-2 left-2 rounded-full bg-danger px-2 py-0.5 text-[11px] text-white">失败</span>
          <span class="cv-scan" />
        </div>

        <div class="flex min-h-0 flex-1 flex-col p-3">
          <b class="ttl-u line-clamp-2 text-[13.5px] leading-[19px] font-semibold [overflow-wrap:anywhere] [word-break:normal]">{{ r.names.join(' vs ') }}</b>
          <p class="mt-1 line-clamp-2 text-[12px] leading-[17px] text-ink-2" :class="{ 'text-danger': r.status === 'failed' }">
            {{ r.status === 'running' ? 'AI 正在对比…' : r.status === 'failed' ? '对比失败，点开可重试' : r.summary }}
          </p>
          <!-- v3.2.1：手机两列时模型标签和时间挤在一行会折行，改为上下排列 -->
          <div class="mt-auto flex min-w-0 flex-col items-start gap-1 pt-2">
            <AiTag v-if="r.status === 'done'" :model="r.model" class="max-w-full" />
            <span class="flex items-center gap-1 text-[11px] whitespace-nowrap text-mute tabular-nums"><Icon name="clock" :size="11" />{{ timeAgo(r.created_at) }}</span>
          </div>
        </div>
      </RouterLink>
    </div>
  </div>
</template>

<style scoped>
.cmp-tile img,
.cmp-tile > div {
  transition: transform 0.6s var(--ease-out-expo);
}
/* v3.3.6：悬停动效只给有鼠标的设备；手机上带 :hover 变化会让 iOS 第一次点按只触发悬停、不跳转 */
@media (hover: hover) and (pointer: fine) {
.cmp-card:hover .cmp-tile:nth-child(odd) img,
.cmp-card:hover .cmp-tile:nth-child(odd) > div {
  transform: translateX(-4px) scale(1.06);
}
.cmp-card:hover .cmp-tile:nth-child(even) img,
.cmp-card:hover .cmp-tile:nth-child(even) > div {
  transform: translateX(4px) scale(1.06);
}
.cmp-vs {
  transition: transform 0.6s var(--ease-spring);
}
.cmp-card:hover .cmp-vs {
  transform: translate(-50%, -50%) rotate(360deg) scale(1.12);
}
}
.cmp-card:active {
  transform: scale(0.985);
}
@media (prefers-reduced-motion: reduce) {
  .cmp-card:hover .cmp-vs,
  .cmp-card:hover .cmp-tile img,
  .cmp-card:hover .cmp-tile > div {
    transform: none;
  }
}
</style>
