<script setup>
import { computed } from 'vue'
import { dock } from '../composables/dock'
import { dockLayout } from '../composables/dockLayout'
import { ghView } from '../composables/ghView'
import { taskState } from '../composables/tasks'
import Icon from './Icon.vue'

// v3.3.26 统一的「加入」栏（GitHub 搜索结果 / 长文识别 / 截图识别共用，与小程序一致）：
// - 只在有勾选时出现；点「加入」后外层立刻清空勾选，栏随之收起，进度看右侧任务浮窗
// - 智能贴底（v3.3.27）：始终在手机底部停靠行（任务 / 对比浮窗）上方，位置由 dockLayout 统一计算
const props = defineProps({
  show: Boolean, // 外层决定：有勾选、不在对比模式、列表在屏幕里……
  count: { type: Number, default: 0 },
  note: { type: String, default: '' }, // 已选数后面的补充（如「另有 2 个加入中」）
  posting: Boolean,
})
const emit = defineEmits(['join'])

const taskBar = computed(() => !(dock.mobile && dock.taskMini) && (taskState.pending.length > 0 || taskState.tasks.some((t) => !taskState.dismissed.has(t.id))))
const bottom = computed(() => {
  if (!dock.mobile) return taskBar.value ? '92px' : '24px'
  return dockLayout.value.joinBottom // v3.3.27 始终在停靠行（任务 / 对比浮窗所在的一行）上方
})
</script>

<template>
  <Teleport to="body">
    <Transition name="toast">
      <div v-if="props.show && count > 0 && ghView.shown" class="fixed inset-x-3 z-[45] mx-auto max-w-[620px] transition-[bottom] duration-300" :style="{ bottom }">
        <div class="glass-strong relative flex items-center gap-3 overflow-hidden rounded-[10px] p-2 pl-4 shadow-[0_16px_36px_-16px_rgb(11_47_122/0.55)]">
          <p class="min-w-0 flex-1 truncate text-[13px] text-ink-2">
            已选 <b class="text-ink tabular-nums">{{ count }}</b> 个<span v-if="note" class="text-brand"> · {{ note }}</span>
          </p>
          <slot name="actions" />
          <button class="btn-primary shrink-0" :disabled="posting" @click="emit('join')">
            <span v-if="posting" class="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-r-transparent" />
            <Icon v-else name="plus" :size="15" class="i-plus" />
            <span>加入 {{ count }} 个</span>
          </button>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>
