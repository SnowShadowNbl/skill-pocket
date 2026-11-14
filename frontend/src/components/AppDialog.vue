<script setup>
import { nextTick, ref, watch } from 'vue'
import { closeDialog, dialogState } from '../composables/dialog'
import Icon from './Icon.vue'

const input = ref(null)
const okBtn = ref(null)

watch(
  () => dialogState.open,
  async (v) => {
    if (!v) return
    await nextTick()
    if (dialogState.kind === 'prompt') {
      input.value?.focus()
      input.value?.select()
    } else okBtn.value?.focus()
  },
)

function onKey(e) {
  if (e.key === 'Escape') closeDialog(false)
}
</script>

<template>
  <Teleport to="body">
    <Transition name="sheet">
      <div
        v-if="dialogState.open"
        class="fixed inset-0 z-[80] grid place-items-end bg-ink/25 backdrop-blur-[4px] sm:place-items-center"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="dlg-title"
        @click.self="closeDialog(false)"
        @keydown="onKey"
      >
        <form
          class="sheet-panel glass-strong pb-safe w-full rounded-t-[14px] p-6 shadow-[0_-24px_60px_-24px_rgb(11_47_122/0.45)] sm:max-w-[400px] sm:rounded-[12px]"
          @submit.prevent="closeDialog(true)"
        >
          <div class="flex items-start gap-3">
            <span
              class="grid h-10 w-10 shrink-0 place-items-center rounded-2xl"
              :class="dialogState.opts.danger ? 'bg-danger-soft text-danger' : 'bg-brand-soft text-brand'"
            >
              <Icon :name="dialogState.opts.icon || (dialogState.opts.danger ? 'alert' : dialogState.kind === 'prompt' ? 'pencil' : 'check')" :size="19" />
            </span>
            <div class="min-w-0 flex-1 pt-1">
              <h2 id="dlg-title" class="text-[17px] font-bold">{{ dialogState.opts.title }}</h2>
              <p v-if="dialogState.opts.message" class="mt-1.5 text-sm leading-relaxed whitespace-pre-line text-ink-2">{{ dialogState.opts.message }}</p>
            </div>
          </div>
          <input
            v-if="dialogState.kind === 'prompt'"
            ref="input"
            v-model="dialogState.value"
            class="field mt-4"
            :placeholder="dialogState.opts.placeholder || ''"
            :maxlength="dialogState.opts.maxlength || 40"
            :aria-label="dialogState.opts.title"
          />
          <div class="mt-6 grid grid-cols-2 gap-2 sm:flex sm:justify-end">
            <button type="button" class="btn-glass" @click="closeDialog(false)">{{ dialogState.opts.cancelText || '取消' }}</button>
            <button
              ref="okBtn"
              type="submit"
              :class="dialogState.opts.danger ? 'btn-danger' : 'btn-primary'"
              :disabled="dialogState.kind === 'prompt' && !dialogState.value.trim()"
            >{{ dialogState.opts.okText || '确定' }}</button>
          </div>
        </form>
      </div>
    </Transition>
  </Teleport>
</template>
