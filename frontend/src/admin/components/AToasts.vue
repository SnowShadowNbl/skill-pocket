<script setup>
import Icon from '../../components/Icon.vue'
import { toasts } from '../../composables/toast'

const STYLE = { success: ['check', 'text-ok'], error: ['alert', 'text-bad'], info: ['message', 'text-primary'] }
</script>

<template>
  <div class="pointer-events-none fixed top-4 left-1/2 z-[60] flex -translate-x-1/2 flex-col items-center gap-2" aria-live="polite">
    <TransitionGroup name="fade">
      <div v-for="t in toasts" :key="t.id" class="flex items-center gap-2 rounded-lg border border-line bg-white px-4 py-2.5 text-[13.5px] shadow-[0_8px_24px_-10px_rgba(15,29,51,.25)]">
        <Icon :name="(STYLE[t.type] || STYLE.info)[0]" :size="16" :class="(STYLE[t.type] || STYLE.info)[1]" />{{ t.message }}
      </div>
    </TransitionGroup>
  </div>
</template>
