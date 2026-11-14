<script setup>
import { useItemLink } from '../composables/itemLink'
import { computed, onBeforeUnmount, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { isCancelled } from '../api'
import { requireLogin } from '../composables/auth'
import {
  COMPARE_MAX, clearCompare, compareState, dismissRun, removeCompare, retryRun, setCompareMode, startCompare,
} from '../composables/compare'
import { dock } from '../composables/dock'
import { dockLayout } from '../composables/dockLayout'
import { toast } from '../composables/toast'
import { formatStars } from '../api'
import Icon from './Icon.vue'
import AiTag from './AiTag.vue'

// 对比面板（v2.6）：像上传进度表一样常驻在页面左下角（手机在底部）。
// 收起时一行概况；展开后能看到每个待对比条目的详细信息、以及每次对比的进度和结果。跨页面一直在。
const itemLink = useItemLink()
const route = useRoute()
const router = useRouter()
const list = computed(() => compareState.list)
const runs = computed(() => compareState.runs)
const running = computed(() => runs.value.filter((r) => r.status === 'running'))
const show = computed(() => !route.path.startsWith('/compare')
  && (compareState.mode || list.value.length > 0 || running.value.length > 0 || compareState.open))
// v3.3.27 手机上的位置统一由 dockLayout 计算（和任务浮窗同一行排开，不再上下错开遮挡）
watch(show, (v) => (dock.compareShown = v), { immediate: true })
onBeforeUnmount(() => (dock.compareShown = false))

const headline = computed(() => {
  if (running.value.length) return `对比中 · ${running.value[0].stage || 'AI 正在分析…'}`
  if (!list.value.length) return '勾选卡片上的「对比」'
  if (list.value.length < 2) return `已选 ${list.value.length} 个，再选 1 个就能对比`
  return `已选 ${list.value.length} 个，可以开始对比`
})

const STATUS = {
  running: ['refresh', 'animate-spin text-brand', '对比中'],
  done: ['check', 'text-ok', '已完成'],
  failed: ['alert', 'text-danger', '失败'],
}

function entryLink(x) {
  if (x.item_id) return { to: itemLink(x.item_id) }
  return { href: `https://github.com/${x.full_name}${x.sub_path ? `/tree/HEAD/${x.sub_path}` : ''}` }
}

async function start() {
  if (list.value.length < 2) return
  if (!(await requireLogin('对比需要先登录（会消耗你的 AI 额度）'))) return
  try {
    await startCompare()
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  }
}

async function retry(r) {
  try {
    await retryRun(r)
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  }
}

function view(r) {
  compareState.open = false
  router.push(`/compare/${r.id}`)
}

function close() {
  compareState.open = false
  // 刚开始对比时对比栏是空的：有进行中的对比就不退出对比模式
  if (!list.value.length && !compareState.runs.some((r) => r.status === 'running')) setCompareMode(false)
}
</script>

<template>
  <!-- 手机：缩成右侧的小圆按钮（任务按钮在下面时往上叠），点开再展开完整面板 -->
  <Transition name="dock">
    <button
      v-if="show && dock.mobile && dock.compareMini"
      class="dock-btn fixed z-40 grid h-12 w-12 cursor-pointer place-items-center rounded-full text-brand"
      :style="dockLayout.compareCircle"
      :aria-label="`AI 智能对比：${headline}，点开查看`"
      @click="(dock.compareMini = false), (compareState.open = running.length > 0 || compareState.open)"
    >
      <Icon :name="running.length ? 'refresh' : 'layers'" :size="19" :class="{ 'animate-spin': running.length }" />
      <span v-if="list.length" class="absolute -top-1 -right-1 grid h-[18px] min-w-[18px] place-items-center rounded-full bg-brand px-1 text-[10.5px] font-semibold text-white">{{ list.length }}</span>
      <span class="absolute -bottom-1 rounded-full bg-brand px-1 text-[8.5px] leading-[13px] font-bold text-white">AI</span>
    </button>
  </Transition>
  <div
    v-if="show && !(dock.mobile && dock.compareMini)"
    class="fixed right-3 left-3 z-40 sm:right-auto sm:bottom-5 sm:left-5 sm:z-[60] sm:w-[400px]"
    :style="dock.mobile ? dockLayout.compareBar : null"
    role="region"
    aria-label="AI 智能对比"
  >
    <Transition name="toast">
      <div v-if="compareState.open" v-scroll-trap class="glass-strong mb-2 max-h-[64vh] overflow-y-auto rounded-[12px] p-3 shadow-[0_20px_50px_-20px_rgb(11_47_122/0.5)]">
        <div class="mb-2 flex items-center gap-2 px-1">
          <p class="text-sm font-semibold">待对比 <span class="font-normal text-mute tabular-nums">{{ list.length }}/{{ COMPARE_MAX }}</span></p>
          <button v-if="list.length" class="ml-auto cursor-pointer text-xs text-mute hover:text-ink" @click="clearCompare">清空</button>
          <button class="grid h-7 w-7 cursor-pointer place-items-center rounded-full text-mute hover:bg-ink/5 hover:text-ink" :class="{ 'ml-auto': !list.length }" aria-label="收起对比面板" @click="close">
            <Icon name="x" :size="15" />
          </button>
        </div>

        <p v-if="!list.length" class="rounded-lg bg-hover p-3 text-[13px] leading-relaxed text-ink-2">勾选卡片上的「对比」，选 2~{{ COMPARE_MAX }} 个</p>
        <ul v-else class="space-y-1.5">
          <li v-for="x in list" :key="x.key" class="flex gap-2.5 rounded-2xl bg-white/60 p-2.5">
            <span class="grid h-11 w-11 shrink-0 place-items-center overflow-hidden rounded-xl bg-ink/5">
              <img v-if="x.cover_url" :src="x.cover_url" alt="" class="h-full w-full object-cover" loading="lazy" />
              <Icon v-else :name="x.external ? 'github' : 'package'" :size="18" class="text-mute" />
            </span>
            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-1.5">
                <RouterLink v-if="entryLink(x).to" :to="entryLink(x).to" class="truncate text-[13.5px] font-semibold hover:text-brand">{{ x.name }}</RouterLink>
                <a v-else :href="entryLink(x).href" target="_blank" rel="noopener" class="truncate text-[13.5px] font-semibold hover:text-brand">{{ x.name }}</a>
                <span class="tag shrink-0" :class="x.external ? 'bg-ink/5 text-ink-2' : 'bg-brand-soft text-brand'">{{ x.external ? 'GitHub' : '本站' }}</span>
              </div>
              <p class="mt-0.5 flex flex-wrap gap-x-2 text-[11.5px] text-mute">
                <span v-if="x.stars != null" class="tabular-nums">★ {{ formatStars(x.stars) }}</span>
                <span v-if="x.category">{{ x.category }}</span>
                <span v-if="x.repo" class="truncate">{{ x.repo }}</span>
              </p>
              <p v-if="x.summary" class="mt-0.5 line-clamp-2 text-[12.5px] leading-snug text-ink-2">{{ x.summary }}</p>
            </div>
            <button class="grid h-7 w-7 shrink-0 cursor-pointer place-items-center rounded-full text-mute hover:bg-danger-soft hover:text-danger" :aria-label="`移除 ${x.name}`" @click="removeCompare(x.key)">
              <Icon name="x" :size="14" />
            </button>
          </li>
        </ul>
        <div v-if="list.length" class="mt-2 flex items-center gap-2 px-1">
          <button class="btn-primary btn-sm ml-auto shrink-0" :disabled="list.length < 2 || compareState.starting" @click="start">
            <Icon :name="compareState.starting ? 'refresh' : 'sparkles'" :size="15" :class="{ 'animate-spin': compareState.starting }" />开始对比
          </button>
        </div>

        <template v-if="runs.length">
          <p class="mt-4 mb-2 px-1 text-sm font-semibold">对比记录</p>
          <ol class="space-y-1.5">
            <li v-for="r in runs" :key="r.id" class="rounded-2xl bg-white/60 p-2.5">
              <div class="flex items-start gap-2">
                <Icon :name="STATUS[r.status]?.[0] || 'clock'" :size="15" class="mt-0.5 shrink-0" :class="STATUS[r.status]?.[1]" />
                <div class="min-w-0 flex-1">
                  <p class="text-[13px] font-medium break-words">{{ r.names.join(' · ') }}</p>
                  <p v-if="r.status === 'running'" class="mt-0.5 text-[12px] text-brand">{{ r.stage || 'AI 正在分析…' }}</p>
                  <p v-else-if="r.status === 'failed'" class="mt-0.5 text-[12px] text-danger">{{ r.error || '对比失败' }}</p>
                  <p v-else-if="r.summary" class="mt-0.5 line-clamp-2 text-[12px] leading-snug text-ink-2">{{ r.summary }}</p>
                  <AiTag v-if="r.status === 'done'" class="mt-1" />
                  <div class="mt-1.5 flex items-center gap-3 text-xs">
                    <button v-if="r.status !== 'failed'" class="cursor-pointer text-brand hover:underline" @click="view(r)">{{ r.status === 'running' ? '打开结果页' : '查看结果' }}</button>
                    <button v-if="r.status === 'failed' && r.picked?.length" class="cursor-pointer text-brand hover:underline" @click="retry(r)">重试</button>
                    <button v-if="r.status !== 'running'" class="cursor-pointer text-mute hover:text-ink" @click="dismissRun(r.id)">移除</button>
                  </div>
                </div>
              </div>
            </li>
          </ol>
          <RouterLink :to="{ path: '/pocket', query: { tab: 'compares' } }" class="mt-2 inline-flex items-center gap-1 px-1 text-xs text-brand hover:underline" @click="compareState.open = false">
            全部对比记录<Icon name="chevron-right" :size="13" />
          </RouterLink>
        </template>
      </div>
    </Transition>

    <div class="glass-strong flex items-center gap-2 rounded-2xl py-2 pr-2 pl-3 shadow-[0_12px_30px_-14px_rgb(11_47_122/0.55)]">
      <button class="flex min-w-0 flex-1 cursor-pointer items-center gap-2.5 text-left" :aria-expanded="compareState.open" @click="compareState.open = !compareState.open">
        <span class="relative grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-brand-soft text-brand">
          <Icon :name="running.length ? 'refresh' : 'layers'" :size="16" :class="{ 'animate-spin': running.length }" />
          <span v-if="list.length" class="absolute -top-1 -right-1 grid h-4.5 min-w-4.5 place-items-center rounded-full bg-brand px-1 text-[10.5px] font-semibold text-white tabular-nums">{{ list.length }}</span>
        </span>
        <span class="min-w-0 flex-1">
          <span class="block text-[13px] font-semibold">AI 智能对比</span>
          <span class="block truncate text-[11.5px] text-mute">{{ headline }}</span>
        </span>
        <Icon name="chevron-up" :size="16" class="shrink-0 text-mute transition-transform duration-300" :class="{ 'rotate-180': compareState.open }" />
      </button>
      <button v-if="list.length >= 2" class="btn-primary btn-sm shrink-0" :disabled="compareState.starting" @click="start">
        <Icon :name="compareState.starting ? 'refresh' : 'sparkles'" :size="15" :class="{ 'animate-spin': compareState.starting }" />对比
      </button>
      <button v-if="dock.mobile" class="grid h-8 w-8 shrink-0 cursor-pointer place-items-center rounded-full text-mute hover:bg-ink/5" aria-label="收起到右侧" @click="(dock.compareMini = true), (compareState.open = false)"><Icon name="minus" :size="16" /></button>
    </div>
  </div>
</template>

<style scoped>
.dock-btn {
  background: rgb(255 255 255 / 0.95);
  border: 1px solid var(--color-line);
  box-shadow: 0 10px 24px -12px rgb(11 47 122 / 0.6);
  backdrop-filter: blur(12px);
}
.dock-enter-active,
.dock-leave-active {
  transition: transform 0.4s var(--ease-spring), opacity 0.25s;
}
.dock-enter-from,
.dock-leave-to {
  opacity: 0;
  transform: translateX(24px) scale(0.6);
}
</style>
