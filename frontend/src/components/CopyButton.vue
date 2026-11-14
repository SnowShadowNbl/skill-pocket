<script setup>
import { track } from '../composables/analytics'
import { ref } from 'vue'
import Icon from './Icon.vue'
import { toast } from '../composables/toast'

const props = defineProps({
  text: String,
  label: { type: String, default: '复制' },
  dark: Boolean, // 放在深色代码块里
  block: Boolean, // 作为操作区里的普通按钮
  icon: { type: String, default: 'copy' },
})
const copied = ref(false)

async function copy() {
  track('copy_prompt', { label: String(props.label || '').slice(0, 40) })
  try {
    await navigator.clipboard.writeText(props.text)
  } catch {
    // 非 HTTPS 环境下 clipboard API 不可用，退回旧方法
    const ta = document.createElement('textarea')
    ta.value = props.text
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    ta.remove()
  }
  copied.value = true
  toast('已复制到剪贴板', 'success', 1500)
  setTimeout(() => (copied.value = false), 1500)
}
</script>

<template>
  <button
    type="button"
    :class="[
      block
        ? ['btn-glass', copied ? 'text-ok' : '']
        : 'inline-flex h-9 shrink-0 cursor-pointer items-center gap-1 rounded-[10px] border px-2.5 text-xs font-medium transition-all duration-300 ease-out-expo active:scale-95 sm:h-8',
      block ? '' : dark
        ? copied ? 'border-emerald-300 text-emerald-300' : 'border-white/20 text-blue-200 hover:bg-white/10'
        : copied ? 'border-ok/30 bg-ok-soft text-ok' : 'border-edge bg-white/70 text-ink-2 hover:bg-white hover:text-ink',
    ]"
    :aria-label="`${label}：${text}`"
    @click.stop.prevent="copy"
  >
    <Icon :name="copied ? 'check' : icon" :size="block ? 16 : 14" />{{ copied ? '已复制' : label }}
  </button>
</template>
