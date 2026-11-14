<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import Icon from '../../components/Icon.vue'
import { closeReason, reasonState } from '../composables/reason'

// 填写原因弹窗：标题、影响摘要、常用原因模板、必填原因（有最短字数）。在 AdminApp 里挂一次
const input = ref(null)
const o = computed(() => reasonState.opts)
const len = computed(() => reasonState.value.trim().length)
const lack = computed(() => Math.max(0, (o.value.min || 0) - len.value))

function onKey(e) {
  if (e.key === 'Escape') closeReason(false)
}
watch(() => reasonState.open, async (v) => {
  if (v) {
    window.addEventListener('keydown', onKey)
    await nextTick()
    input.value?.focus()
  } else window.removeEventListener('keydown', onKey)
})
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <Transition name="fade">
    <div v-if="reasonState.open" class="fixed inset-0 z-50 grid place-items-end bg-ink/35 sm:place-items-center sm:px-4" @click.self="closeReason(false)">
      <form
        class="card w-full rounded-b-none p-5 shadow-[0_20px_50px_-20px_rgba(15,29,51,.35)] sm:max-w-[460px] sm:rounded-b-lg sm:p-6"
        role="dialog"
        aria-modal="true"
        :aria-label="o.title"
        @submit.prevent="!lack && closeReason(true)"
      >
        <h2 class="m-0 text-base font-semibold">{{ o.title }}</h2>
        <p
          v-if="o.impact"
          class="mt-3 mb-0 flex items-start gap-2 rounded-md px-3 py-2 text-[13px] font-medium"
          :class="o.danger ? 'bg-bad-soft text-bad' : 'bg-warn-soft text-warn'"
        >
          <Icon name="alert" :size="15" class="mt-0.5 shrink-0" /><span>{{ o.impact }}</span>
        </p>
        <div v-if="o.templates.length" class="mt-4 flex flex-wrap gap-1.5">
          <button
            v-for="t in o.templates"
            :key="t"
            type="button"
            class="seg-chip"
            :class="{ on: reasonState.value === t }"
            @click="reasonState.value = t; input?.focus()"
          >{{ t }}</button>
        </div>
        <textarea
          ref="input"
          v-model="reasonState.value"
          class="input mt-3 h-24 resize-none py-2"
          :placeholder="o.placeholder || '填写原因（会记入操作日志）'"
          :maxlength="o.max"
          aria-label="原因"
        />
        <p class="mt-1 mb-0 flex text-xs" :class="lack ? 'text-warn' : 'text-mute'">
          <span>{{ lack ? `还差 ${lack} 字` : '' }}</span><span class="ml-auto tabular-nums">{{ len }} / {{ o.max }}</span>
        </p>
        <div class="mt-5 flex justify-end gap-2">
          <button type="button" class="btn" @click="closeReason(false)">取消</button>
          <button class="btn" :disabled="!!lack" :class="o.danger ? 'border-bad bg-bad text-white hover:!bg-[#d33b40]' : 'btn-primary'">{{ o.okText || '确定' }}</button>
        </div>
      </form>
    </div>
  </Transition>
</template>

<style scoped>
.seg-chip { height: 28px; padding: 0 10px; border: 1px solid var(--color-line); border-radius: 14px; background: #fff; color: var(--color-ink-2); font-size: 12.5px; cursor: pointer; transition: border-color .2s, color .2s, background-color .2s; }
.seg-chip:hover { border-color: var(--color-primary); color: var(--color-primary); }
.seg-chip.on { border-color: var(--color-primary); background: var(--color-primary-soft); color: var(--color-primary); }
</style>
