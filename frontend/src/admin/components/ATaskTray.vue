<script setup>
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import Icon from '../../components/Icon.vue'
import { dismissTask, refreshTasks, taskState } from '../../composables/tasks'

// 管理端右下角的任务进度：所有人的采集、导入、批量处理等任务实时显示（运行中每 2 秒刷新，空闲 15 秒）
const open = ref(false)
const visible = computed(() => taskState.tasks.filter((t) => !taskState.dismissed.has(t.id)))
const running = computed(() => visible.value.filter((t) => t.status === 'running'))
const head = computed(() => running.value[0] || visible.value[0])

const pct = (t) => (t.total ? Math.round((t.done / t.total) * 100) : 100)
function headline(t) {
  if (t.status === 'running') {
    const cur = t.items?.find((i) => i.status === 'running')
    return cur ? `${t.kind_label} ${t.done + 1}/${t.total} · ${cur.name}` : `${t.kind_label} ${t.done}/${t.total}`
  }
  const ok = t.done - t.failed
  return `${t.kind_label}完成：成功 ${ok}${t.failed ? `，失败 ${t.failed}` : ''}${t.done < t.total ? `，${t.total - t.done} 个留到下次` : ''}`
}
const ICON = { pending: ['clock', 'text-mute'], running: ['refresh', 'animate-spin text-primary'], ok: ['check', 'text-ok'], failed: ['alert', 'text-bad'], deferred: ['clock', 'text-warn'] }

function clearDone() {
  visible.value.filter((t) => t.status !== 'running').forEach((t) => dismissTask(t.id))
  open.value = false
}
onMounted(refreshTasks)
</script>

<template>
  <div v-if="head" class="fixed right-4 bottom-4 left-4 z-30 sm:left-auto sm:w-[400px]" aria-live="polite">
    <Transition name="fade">
      <div v-if="open" class="mb-2 max-h-[60vh] overflow-y-auto rounded-xl border border-line bg-white p-3 shadow-[0_16px_40px_-16px_rgba(15,29,51,.35)]">
        <div class="mb-2 flex items-center px-1">
          <p class="m-0 text-sm font-semibold">任务进度</p>
          <span v-if="running.length" class="tag tag-blue ml-2">{{ running.length }} 个进行中</span>
          <button class="ml-auto text-xs text-mute hover:text-ink" @click="clearDone">清除已完成</button>
        </div>
        <section v-for="t in visible" :key="t.id" class="mb-2 rounded-lg border border-line p-3 last:mb-0">
          <div class="flex items-center gap-2">
            <span class="tag" :class="t.source === 'auto' ? 'tag-ok' : 'tag-blue'">{{ t.source === 'auto' ? '系统' : '人工' }}</span>
            <p class="m-0 min-w-0 flex-1 truncate text-[13px] font-medium">{{ t.title }}</p>
            <span class="text-xs text-mute tabular-nums">{{ t.done }}/{{ t.total }}</span>
          </div>
          <div class="mt-2 h-1.5 overflow-hidden rounded-full bg-[#e9edf3]">
            <div class="h-full rounded-full transition-[width] duration-700" :class="t.failed ? 'bg-warn' : 'bg-primary'" :style="{ width: pct(t) + '%' }" />
          </div>
          <ol class="m-0 mt-2 list-none space-y-1 p-0">
            <li v-for="i in t.items" :key="i.seq" class="flex items-start gap-2 text-[12.5px]">
              <Icon :name="ICON[i.status]?.[0] || 'clock'" :size="13" class="mt-0.5 shrink-0" :class="ICON[i.status]?.[1]" />
              <span class="w-7 shrink-0 text-right text-mute tabular-nums">{{ i.seq }}</span>
              <div class="min-w-0 flex-1">
                <span class="font-medium">{{ i.name }}</span>
                <span v-if="i.status === 'running'" class="ml-1 text-primary">· {{ i.stage_label }}</span>
                <p v-if="i.message && i.status !== 'running'" class="m-0 truncate text-mute" :class="{ 'text-bad': i.status === 'failed' }" :title="i.message">{{ i.message }}</p>
              </div>
            </li>
          </ol>
          <RouterLink :to="{ path: '/logs', query: { task: t.id } }" class="mt-2 inline-flex items-center gap-1 text-xs text-primary hover:underline" @click="open = false">
            查看这批的入库日志<Icon name="chevron-right" :size="13" />
          </RouterLink>
        </section>
      </div>
    </Transition>
    <button class="flex w-full items-center gap-3 rounded-xl border border-line bg-white px-3.5 py-2.5 text-left shadow-[0_10px_28px_-14px_rgba(15,29,51,.35)]" :aria-expanded="open" @click="open = !open">
      <span class="relative grid h-8 w-8 shrink-0 place-items-center">
        <svg viewBox="0 0 36 36" class="absolute inset-0 -rotate-90">
          <circle cx="18" cy="18" r="15" fill="none" stroke="#e9edf3" stroke-width="3.5" />
          <circle cx="18" cy="18" r="15" fill="none" stroke="#1e56d6" stroke-width="3.5" stroke-linecap="round" :stroke-dasharray="94.25" :stroke-dashoffset="94.25 * (1 - pct(head) / 100)" class="transition-[stroke-dashoffset] duration-700" />
        </svg>
        <Icon v-if="head.status === 'running'" name="refresh" :size="13" class="animate-spin text-primary" />
        <Icon v-else :name="head.failed ? 'alert' : 'check'" :size="14" :class="head.failed ? 'text-warn' : 'text-ok'" />
      </span>
      <span class="min-w-0 flex-1">
        <span class="block truncate text-[13px] font-medium">{{ headline(head) }}</span>
        <span class="block text-xs text-mute">{{ running.length ? `${running.length} 个任务进行中` : '点开查看结果' }}<template v-if="visible.length > 1"> · 共 {{ visible.length }} 个</template></span>
      </span>
      <Icon name="chevron-up" :size="15" class="text-mute transition-transform" :class="{ 'rotate-180': open }" />
    </button>
  </div>
</template>
