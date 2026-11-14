<script setup>
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import Icon from '../../components/Icon.vue'

// 右侧详情抽屉（手机上全屏）。插槽：header（标题区）/ 默认（内容，可滚动）/ footer（底部操作）
//   <ADrawer :open="!!detail.id" label="用户详情" @close="detail.close()">…</ADrawer>
const props = defineProps({
  open: Boolean,
  label: { type: String, default: '详情' },
  width: { type: Number, default: 600 },
})
const emit = defineEmits(['close'])
const panel = ref(null)
let opener = null

function onKey(e) {
  if (e.key !== 'Escape') return
  // 抽屉上层还有弹窗（确认 / 原因）时，Esc 先交给弹窗
  if (document.querySelector('[role="dialog"][aria-modal="true"]')) return
  emit('close')
}
watch(() => props.open, async (v) => {
  if (v) {
    opener = document.activeElement
    document.documentElement.style.overflow = 'hidden'
    window.addEventListener('keydown', onKey)
    await nextTick()
    panel.value?.focus()
  } else {
    document.documentElement.style.overflow = ''
    window.removeEventListener('keydown', onKey)
    opener?.focus?.()
    opener = null
  }
}, { immediate: true })
onBeforeUnmount(() => {
  document.documentElement.style.overflow = ''
  window.removeEventListener('keydown', onKey)
})
</script>

<template>
  <Teleport to="body">
    <Transition name="drawer">
      <div v-if="open" class="fixed inset-0 z-40 bg-ink/30" @click.self="emit('close')">
        <aside
          ref="panel"
          tabindex="-1"
          class="absolute inset-y-0 right-0 flex w-full flex-col bg-white shadow-[-12px_0_40px_-20px_rgba(15,29,51,.35)] outline-none"
          :style="{ maxWidth: `${width}px` }"
          role="dialog"
          :aria-label="label"
        >
          <header class="flex items-center gap-3 border-b border-line px-5 py-4">
            <div class="min-w-0 flex-1"><slot name="header" /></div>
            <button class="btn h-9 w-9 shrink-0 px-0" aria-label="关闭" @click="emit('close')"><Icon name="x" :size="17" /></button>
          </header>
          <div class="flex-1 overflow-y-auto overscroll-contain px-5 py-4"><slot /></div>
          <footer v-if="$slots.footer" class="border-t border-line px-5 py-3 pb-[max(12px,env(safe-area-inset-bottom))]"><slot name="footer" /></footer>
        </aside>
      </div>
    </Transition>
  </Teleport>
</template>
