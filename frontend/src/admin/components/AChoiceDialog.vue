<script setup>
import { computed, onBeforeUnmount, watch } from 'vue'
import Icon from '../../components/Icon.vue'
import { choiceState, closeChoice } from '../composables/choice'
import ASelect from './ASelect.vue'

// 选一项的确认弹窗（如批量改分类选目标分类）。在 AdminApp 里挂一次
const o = computed(() => choiceState.opts)
const options = computed(() => [{ value: '', label: o.value.placeholder || '请选择…' }, ...(o.value.options || [])])
const onKey = (e) => e.key === 'Escape' && closeChoice(false)
watch(() => choiceState.open, (v) => (v ? window.addEventListener('keydown', onKey) : window.removeEventListener('keydown', onKey)))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <Transition name="fade">
    <div v-if="choiceState.open" class="fixed inset-0 z-50 grid place-items-end bg-ink/35 sm:place-items-center sm:px-4" @click.self="closeChoice(false)">
      <form class="card w-full rounded-b-none p-5 shadow-[0_20px_50px_-20px_rgba(15,29,51,.35)] sm:max-w-[420px] sm:rounded-b-lg sm:p-6" role="dialog" aria-modal="true" :aria-label="o.title" @submit.prevent="closeChoice(true)">
        <h2 class="m-0 text-base font-semibold">{{ o.title }}</h2>
        <p v-if="o.impact" class="mt-3 mb-0 flex items-start gap-2 rounded-md bg-warn-soft px-3 py-2 text-[13px] font-medium text-warn"><Icon name="alert" :size="15" class="mt-0.5 shrink-0" /><span>{{ o.impact }}</span></p>
        <div class="mt-4"><ASelect v-model="choiceState.value" :options="options" :label="o.title" searchable /></div>
        <div class="mt-5 flex justify-end gap-2">
          <button type="button" class="btn" @click="closeChoice(false)">取消</button>
          <button class="btn btn-primary" :disabled="choiceState.value === ''">{{ o.okText || '确定' }}</button>
        </div>
      </form>
    </div>
  </Transition>
</template>
