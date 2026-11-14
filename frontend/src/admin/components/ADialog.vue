<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { closeDialog, dialogState } from '../../composables/dialog'

// 管理端样式的确认 / 输入对话框（状态与主站共用 composables/dialog）
const input = ref(null)
// 必填的输入（如驳回原因）没填时不能确定
const blocked = computed(() => dialogState.kind === 'prompt' && dialogState.opts.required && !dialogState.value.trim())
watch(() => dialogState.open, async (v) => {
  if (v && dialogState.kind === 'prompt') {
    await nextTick()
    input.value?.focus()
  }
})
</script>

<template>
  <Transition name="fade">
    <div v-if="dialogState.open" class="fixed inset-0 z-50 grid place-items-center bg-ink/35 px-4" @click.self="closeDialog(false)" @keydown.esc="closeDialog(false)">
      <form class="card w-full max-w-[420px] p-6 shadow-[0_20px_50px_-20px_rgba(15,29,51,.35)]" role="dialog" aria-modal="true" @submit.prevent="!blocked && closeDialog(true)">
        <h2 class="m-0 text-base font-semibold">{{ dialogState.opts.title }}</h2>
        <p v-if="dialogState.opts.message" class="mt-2 text-sm whitespace-pre-line text-ink-2">{{ dialogState.opts.message }}</p>
        <textarea
          v-if="dialogState.kind === 'prompt'"
          ref="input"
          v-model="dialogState.value"
          class="input mt-4 h-24 resize-none py-2"
          :placeholder="dialogState.opts.placeholder || ''"
          :maxlength="dialogState.opts.maxlength || 300"
        />
        <div class="mt-6 flex justify-end gap-2">
          <button type="button" class="btn" @click="closeDialog(false)">{{ dialogState.opts.cancelText || '取消' }}</button>
          <button class="btn" :disabled="blocked" :class="dialogState.opts.danger ? 'border-bad bg-bad text-white hover:!bg-[#d33b40]' : 'btn-primary'">
            {{ dialogState.opts.okText || '确定' }}
          </button>
        </div>
      </form>
    </div>
  </Transition>
</template>
