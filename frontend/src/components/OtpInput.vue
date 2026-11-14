<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'

// 6 位验证码：一个真实的输入框（支持粘贴、系统自动填充短信 / 邮件验证码），上面叠 6 个格子做展示
const model = defineModel({ type: String, default: '' })
const props = defineProps({ length: { type: Number, default: 6 }, error: Boolean, disabled: Boolean, autofocus: Boolean })
const emit = defineEmits(['complete'])

const input = ref(null)
const focused = ref(false)
const cells = computed(() => Array.from({ length: props.length }, (_, i) => model.value[i] || ''))

function onInput(e) {
  const v = e.target.value.replace(/\D/g, '').slice(0, props.length)
  model.value = v
  e.target.value = v
  if (v.length === props.length) emit('complete', v)
}

function focus() {
  input.value?.focus()
}
defineExpose({ focus })
onMounted(() => props.autofocus && nextTick(focus))
</script>

<template>
  <div class="relative" @click="focus">
    <input
      ref="input"
      :value="model"
      class="absolute inset-0 h-full w-full cursor-text opacity-0"
      inputmode="numeric"
      autocomplete="one-time-code"
      :maxlength="length"
      :disabled="disabled"
      aria-label="验证码"
      @input="onInput"
      @focus="focused = true"
      @blur="focused = false"
    />
    <div class="pointer-events-none grid gap-2" :style="{ gridTemplateColumns: `repeat(${length}, minmax(0, 1fr))` }" aria-hidden="true">
      <span
        v-for="(c, i) in cells"
        :key="i"
        class="relative grid h-14 place-items-center rounded-2xl border bg-white/75 text-2xl font-bold tabular-nums transition-all duration-200"
        :class="[
          error ? 'border-danger/50 text-danger' : c ? 'border-brand/40 text-ink' : 'border-edge text-ink',
          focused && i === Math.min(model.length, length - 1) && !error ? 'ring-2 ring-brand/50' : '',
        ]"
      >
        {{ c }}
        <span v-if="focused && !c && i === model.length" class="caret absolute h-6 w-0.5 rounded bg-brand" />
      </span>
    </div>
  </div>
</template>

<style scoped>
.caret {
  animation: blink 1s steps(1) infinite;
}
@keyframes blink {
  50% { opacity: 0; }
}
</style>
