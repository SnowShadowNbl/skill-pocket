<script setup>
import { computed, ref } from 'vue'

// v3.3 好用度星星：只读时按分值填充（支持半星），可编辑时悬停预览、点击打分、再点同一颗取消
const props = defineProps({
  modelValue: { type: Number, default: 0 },
  editable: Boolean,
  size: { type: Number, default: 14 },
})
const emit = defineEmits(['update:modelValue'])
const hover = ref(0)
const shown = computed(() => hover.value || props.modelValue || 0)
const LABELS = ['', '不好用', '一般', '还行', '好用', '强烈推荐']
const label = computed(() => LABELS[Math.round(shown.value)] || '')

function fill(i) {
  return Math.max(0, Math.min(1, shown.value - (i - 1))) * 100
}
function pick(i) {
  if (!props.editable) return
  emit('update:modelValue', props.modelValue === i ? 0 : i)
}
</script>

<template>
  <span class="inline-flex items-center gap-1.5" :class="{ editable }" @mouseleave="hover = 0">
    <span class="inline-flex" :role="editable ? 'radiogroup' : 'img'" :aria-label="editable ? '好用度' : `好用度 ${modelValue} 分`">
      <component
        :is="editable ? 'button' : 'span'"
        v-for="i in 5"
        :key="i"
        :type="editable ? 'button' : undefined"
        class="star relative inline-block"
        :class="{ 'cursor-pointer': editable, pop: editable && modelValue === i }"
        :style="{ width: `${size}px`, height: `${size}px` }"
        :aria-label="editable ? `${i} 星：${LABELS[i]}` : undefined"
        :role="editable ? 'radio' : undefined"
        :aria-checked="editable ? modelValue === i : undefined"
        @mouseenter="editable && (hover = i)"
        @click="pick(i)"
      >
        <svg viewBox="0 0 24 24" class="absolute inset-0 h-full w-full text-line"><path fill="currentColor" d="M12 2.5l2.9 6 6.6.9-4.8 4.6 1.2 6.5L12 17.4l-5.9 3.1 1.2-6.5-4.8-4.6 6.6-.9z" /></svg>
        <span class="absolute inset-0 overflow-hidden" :style="{ width: `${fill(i)}%` }">
          <svg viewBox="0 0 24 24" class="h-full text-amber-400" :style="{ width: `${size}px` }"><path fill="currentColor" d="M12 2.5l2.9 6 6.6.9-4.8 4.6 1.2 6.5L12 17.4l-5.9 3.1 1.2-6.5-4.8-4.6 6.6-.9z" /></svg>
        </span>
      </component>
    </span>
    <span v-if="editable" class="min-w-[4em] text-[12px] text-mute">{{ label || '给个好用度（可选）' }}</span>
  </span>
</template>

<style scoped>
.editable .star {
  transition: transform 0.35s var(--ease-spring);
}
.editable .star:hover {
  transform: scale(1.2);
}
.star.pop {
  animation: starpop 0.45s var(--ease-spring);
}
@keyframes starpop {
  40% {
    transform: scale(1.35) rotate(-8deg);
  }
}
</style>
