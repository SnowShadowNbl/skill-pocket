<script setup>
import Icon from './Icon.vue'

// 主题勾选框（替代原生 checkbox）：checked 为 true / false / 'mixed'
defineProps({
  checked: { type: [Boolean, String], default: false },
  label: { type: String, default: '' },
  tone: { type: String, default: 'brand' }, // brand：品牌色 / compare：对比（渐变）
  disabled: Boolean,
})
defineEmits(['toggle'])
</script>

<template>
  <button
    type="button"
    role="checkbox"
    :aria-checked="checked === 'mixed' ? 'mixed' : !!checked"
    :aria-label="label || undefined"
    :disabled="disabled"
    class="grid h-[18px] w-[18px] shrink-0 cursor-pointer place-items-center rounded-[5px] border-[1.5px] transition-all duration-200 disabled:cursor-default disabled:opacity-40"
    :class="checked
      ? tone === 'compare' ? 'border-transparent bg-brand text-white' : 'border-brand bg-brand text-white'
      : 'border-ink/25 bg-white/80 hover:border-brand'"
    @click.stop="!disabled && $emit('toggle')"
  >
    <Icon v-if="checked === 'mixed'" name="minus" :size="12" />
    <Icon v-else-if="checked" name="check" :size="12" />
  </button>
</template>
