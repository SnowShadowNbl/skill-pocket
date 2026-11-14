<script setup>
// 管理端开关（不用原生 checkbox）：带文字的小按钮，样式同主站「AI 智能对比」开关
defineProps({ modelValue: Boolean, label: { type: String, default: '' } })
defineEmits(['update:modelValue'])
</script>

<template>
  <button
    type="button"
    role="switch"
    :aria-checked="modelValue"
    class="rp flex h-9 shrink-0 cursor-pointer items-center gap-2 rounded-md border px-3 text-[13px] transition-[color,background-color,border-color] duration-300"
    :class="modelValue ? 'border-primary bg-primary-soft font-medium text-primary' : 'border-line bg-white text-ink-2 hover:border-primary hover:text-primary'"
    @click="$emit('update:modelValue', !modelValue)"
  >
    {{ label }}
    <span class="relative h-[18px] w-8 rounded-full transition-colors" :class="modelValue ? 'bg-primary' : 'bg-ink/15'">
      <span class="absolute top-[2px] h-[14px] w-[14px] rounded-full bg-white shadow transition-[left] duration-300" :class="modelValue ? 'left-[16px]' : 'left-[2px]'" />
    </span>
  </button>
</template>
