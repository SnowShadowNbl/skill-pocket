<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { isAdminUser } from '../composables/auth'
import { dismissTask, refreshTasks, taskState } from '../composables/tasks'
import { dock } from '../composables/dock'
import { dockLayout } from '../composables/dockLayout'
import Icon from './Icon.vue'

const open = ref(false)

const visible = computed(() => [...taskState.pending, ...taskState.tasks.filter((t) => !taskState.dismissed.has(t.id))])
const running = computed(() => visible.value.filter((t) => t.status === 'running'))
const head = computed(() => running.value[0] || visible.value[0])
watch(head, (h) => (dock.taskShown = !!h), { immediate: true })
onBeforeUnmount(() => (dock.taskShown = false))

function pct(t) {
  return t.total ? Math.round((t.done / t.total) * 100) : 100
}
function currentItem(t) {
  return t.items?.find((i) => i.status === 'running')
}
function headline(t) {
  if (t.pending) return t.message
  if (t.status === 'running') {
    const cur = currentItem(t)
    return cur ? `${t.kind_label} ${t.done + 1}/${t.total} · ${cur.name} · ${cur.stage_label}` : `${t.kind_label} ${t.done}/${t.total}`
  }
  const ok = t.done - t.failed
  return `${t.kind_label}完成：成功 ${ok} 个${t.failed ? `，失败 ${t.failed} 个` : ''}${t.done < t.total ? `，${t.total - t.done} 个留到下次` : ''}`
}

const STATUS_ICON = {
  pending: ['clock', 'text-mute'],
  running: ['refresh', 'animate-spin text-brand'],
  ok: ['check', 'text-ok'],
  failed: ['alert', 'text-danger'],
  deferred: ['clock', 'text-warn'],
}

function closeAll() {
  visible.value.filter((t) => t.status !== 'running').forEach((t) => dismissTask(t.id))
  open.value = false
}

onMounted(refreshTasks)
</script>

<template>
  <!-- 手机：缩成右侧的小圆按钮（进度环 + 数量），点开再展开完整浮窗 -->
  <Transition name="dock">
    <button
      v-if="head && dock.mobile && dock.taskMini"
      class="dock-btn fixed z-40 grid h-12 w-12 cursor-pointer place-items-center rounded-full"
      :style="dockLayout.taskCircle"
      :aria-label="`任务进度：${headline(head)}，点开查看`"
      @click="dock.taskMini = false"
    >
      <svg viewBox="0 0 36 36" class="absolute inset-1 -rotate-90">
        <circle cx="18" cy="18" r="15" fill="none" stroke="rgb(30 27 75 / 0.1)" stroke-width="3" />
        <circle cx="18" cy="18" r="15" fill="none" stroke="#1E56D6" stroke-width="3" stroke-linecap="round" :stroke-dasharray="94.25" :stroke-dashoffset="94.25 * (1 - pct(head) / 100)" class="transition-[stroke-dashoffset] duration-700" />
      </svg>
      <Icon v-if="head.status === 'running'" name="refresh" :size="15" class="animate-spin text-brand" />
      <Icon v-else :name="head.failed ? 'alert' : 'check'" :size="16" :class="head.failed ? 'text-warn' : 'text-ok'" />
      <span v-if="visible.length > 1" class="absolute -top-1 -right-1 grid h-[18px] min-w-[18px] place-items-center rounded-full bg-brand px-1 text-[10.5px] font-semibold text-white">{{ visible.length }}</span>
    </button>
  </Transition>
  <div
    v-if="head && !(dock.mobile && dock.taskMini)"
    class="fixed right-3 bottom-[calc(76px+env(safe-area-inset-bottom))] left-3 z-40 transition-[right,bottom] duration-300 sm:bottom-5 sm:left-auto sm:w-[380px]"
    :style="dock.mobile ? dockLayout.taskBar : null"
    aria-live="polite"
  >
    <Transition name="toast">
      <div v-if="open" v-scroll-trap class="glass-strong mb-2 max-h-[60vh] overflow-y-auto rounded-[12px] p-3 shadow-[0_20px_50px_-20px_rgb(11_47_122/0.5)]">
        <div class="mb-2 flex items-center px-1">
          <p class="text-sm font-semibold">任务进度</p>
          <button class="ml-auto cursor-pointer text-xs text-mute hover:text-ink" @click="closeAll">清除已完成</button>
        </div>
        <section v-for="t in visible" :key="t.id" class="mb-2 rounded-2xl bg-white/60 p-3 last:mb-0">
          <div class="flex items-center gap-2">
            <span class="tag" :class="t.source === 'auto' ? 'bg-ok-soft text-ok' : 'bg-brand-soft text-brand'">{{ t.source === 'auto' ? '系统' : '人工' }}</span>
            <p class="min-w-0 flex-1 truncate text-[13px] font-medium">{{ t.title }}</p>
            <span v-if="!t.pending" class="text-xs text-mute tabular-nums">{{ t.done }}/{{ t.total }}</span>
          </div>
          <p v-if="t.pending" class="mt-1.5 text-[12.5px] text-brand">{{ t.message }}</p>
          <div v-if="t.pending" class="skeleton-bar mt-2 h-1.5 rounded-full" />
          <div v-else class="mt-2 h-1.5 overflow-hidden rounded-full bg-ink/10">
            <div
              class="h-full rounded-full transition-[width] duration-700 ease-out-expo"
              :class="t.failed ? 'bg-linear-90 from-brand to-warn' : 'bg-linear-90 from-brand to-brand-2'"
              :style="{ width: pct(t) + '%' }"
            />
          </div>
          <ol class="mt-2 space-y-1">
            <li v-for="i in t.items" :key="i.seq" class="flex items-start gap-2 text-[12.5px]">
              <Icon :name="STATUS_ICON[i.status]?.[0]" :size="14" class="mt-0.5 shrink-0" :class="STATUS_ICON[i.status]?.[1]" />
              <span class="w-5 shrink-0 text-right text-mute tabular-nums">{{ i.seq }}</span>
              <div class="min-w-0 flex-1">
                <span class="font-medium">{{ i.name }}</span>
                <span v-if="i.status === 'running'" class="ml-1 text-brand">· {{ i.stage_label }}</span>
                <p v-if="i.message && i.status !== 'running'" class="truncate text-mute" :class="{ 'text-danger': i.status === 'failed' }" :title="i.message">{{ i.message }}</p>
              </div>
            </li>
          </ol>
          <template v-if="t.pending" />
          <a v-else-if="isAdminUser()" :href="`/admin/logs?task=${t.id}`" class="mt-2 inline-flex cursor-pointer items-center gap-1 text-xs text-brand hover:underline">
            查看这批的入库日志<Icon name="chevron-right" :size="13" />
          </a>
          <RouterLink v-else :to="{ path: '/me', query: { tab: 'logs', task: t.id } }" class="mt-2 inline-flex cursor-pointer items-center gap-1 text-xs text-brand hover:underline" @click="open = false">
            查看这批的入库日志<Icon name="chevron-right" :size="13" />
          </RouterLink>
        </section>
      </div>
    </Transition>

    <button
      class="glass-strong flex w-full cursor-pointer items-center gap-3 rounded-2xl px-3.5 py-2.5 text-left shadow-[0_12px_30px_-14px_rgb(11_47_122/0.55)] transition-transform duration-300 ease-out-expo active:scale-[0.98]"
      :aria-expanded="open"
      @click="open = !open"
    >
      <span class="relative grid h-9 w-9 shrink-0 place-items-center">
        <svg viewBox="0 0 36 36" class="absolute inset-0 -rotate-90">
          <circle cx="18" cy="18" r="15" fill="none" stroke="rgb(30 27 75 / 0.1)" stroke-width="3" />
          <circle
            cx="18" cy="18" r="15" fill="none" stroke="url(#tray-grad)" stroke-width="3" stroke-linecap="round"
            :stroke-dasharray="94.25" :stroke-dashoffset="94.25 * (1 - pct(head) / 100)"
            class="transition-[stroke-dashoffset] duration-700"
          />
          <defs><linearGradient id="tray-grad"><stop offset="0" stop-color="#1E56D6" /><stop offset="1" stop-color="#5AA2FF" /></linearGradient></defs>
        </svg>
        <Icon v-if="head.status === 'running'" name="refresh" :size="14" class="animate-spin text-brand" />
        <Icon v-else :name="head.failed ? 'alert' : 'check'" :size="15" :class="head.failed ? 'text-warn' : 'text-ok'" />
      </span>
      <span class="min-w-0 flex-1">
        <span class="block truncate text-[13px] font-medium">{{ headline(head) }}</span>
        <span class="block text-[11.5px] text-mute">
          {{ running.length > 1 ? `另有 ${running.length - 1} 个任务进行中 · ` : '' }}点开查看每一个的进度
        </span>
      </span>
      <Icon name="chevron-up" :size="16" class="shrink-0 text-mute transition-transform duration-300" :class="{ 'rotate-180': open }" />
      <span v-if="dock.mobile" role="button" tabindex="0" class="-mr-1.5 grid h-8 w-8 shrink-0 place-items-center rounded-full text-mute hover:bg-ink/5" aria-label="收起到右侧" @click.stop="(dock.taskMini = true), (open = false)"><Icon name="minus" :size="16" /></span>
    </button>
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
