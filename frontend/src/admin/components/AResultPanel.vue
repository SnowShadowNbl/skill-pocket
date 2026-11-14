<script setup>
import { computed, ref, watch } from 'vue'
import Icon from '../../components/Icon.vue'
import { toast } from '../../composables/toast'
import ASwitch from './ASwitch.vue'

// 批量执行的逐项结果：成功 / 失败及原因；可只看失败、只重试失败项、复制失败清单
//   <AResultPanel :open :title :results="[{ id, label, ok, code, message }]" :retrying @retry="(failedIds) => …" @close />
const props = defineProps({
  open: Boolean,
  title: { type: String, default: '执行结果' },
  results: { type: Array, default: () => [] },
  retrying: Boolean,
})
const emit = defineEmits(['retry', 'close'])
const onlyFail = ref(false)
const failed = computed(() => props.results.filter((r) => !r.ok))
const okCount = computed(() => props.results.length - failed.value.length)
const shown = computed(() => (onlyFail.value ? failed.value : props.results))
watch(() => props.open, (v) => v && (onlyFail.value = false))
// 成功但带说明的结果码（批量接口约定）；失败的显示服务端给的原因
const OK_CODE = { noop: '已是目标状态', queued: '已加入队列', locked_skipped: '已跳过（人工设置过）', has_cover: '已有封面，无需补' }
const reasonOf = (r) => (r.ok ? r.message || OK_CODE[r.code] || '' : r.message || r.code || '失败')

async function copyFailed() {
  const text = failed.value.map((r) => `${r.id}\t${r.label || ''}\t${reasonOf(r)}`).join('\n')
  try {
    await navigator.clipboard.writeText(text)
    toast(`已复制 ${failed.value.length} 条失败清单`, 'success')
  } catch {
    toast('复制失败，请手动选中复制', 'error')
  }
}
</script>

<template>
  <Transition name="fade">
    <div v-if="open" class="fixed inset-0 z-50 grid bg-ink/35 sm:place-items-center sm:px-4" @click.self="emit('close')" @keydown.esc="emit('close')">
      <section class="card flex h-dvh w-full flex-col rounded-none shadow-[0_20px_50px_-20px_rgba(15,29,51,.35)] sm:h-auto sm:max-h-[80vh] sm:max-w-[560px] sm:rounded-lg" role="dialog" aria-modal="true" :aria-label="title">
        <header class="flex items-center gap-3 border-b border-line px-5 py-4">
          <div class="min-w-0 flex-1">
            <h2 class="m-0 text-base font-semibold">{{ title }}</h2>
            <p class="m-0 mt-0.5 text-[13px]"><span class="text-ok">成功 {{ okCount }}</span><span class="mx-2 text-line">|</span><span :class="failed.length ? 'text-bad' : 'text-mute'">失败 {{ failed.length }}</span></p>
          </div>
          <button class="btn h-9 w-9 shrink-0 px-0" aria-label="关闭" @click="emit('close')"><Icon name="x" :size="17" /></button>
        </header>
        <div v-if="failed.length" class="flex flex-wrap items-center gap-2 border-b border-line px-5 py-2.5">
          <ASwitch v-model="onlyFail" label="只看失败" />
          <button class="btn h-9" @click="copyFailed"><Icon name="copy" :size="14" />复制失败清单</button>
        </div>
        <ul class="m-0 min-h-0 flex-1 list-none overflow-y-auto p-0">
          <li v-for="r in shown" :key="r.id" class="flex items-start gap-2.5 border-b border-line px-5 py-2.5 text-[13px] last:border-0">
            <Icon :name="r.ok ? 'check' : 'alert'" :size="15" class="mt-0.5 shrink-0" :class="r.ok ? 'text-ok' : 'text-bad'" />
            <span class="min-w-0 flex-1"><b class="font-medium">{{ r.label || `#${r.id}` }}</b><span v-if="reasonOf(r)" class="block break-words text-xs" :class="r.ok ? 'text-mute' : 'text-bad'">{{ reasonOf(r) }}</span></span>
          </li>
        </ul>
        <footer class="flex justify-end gap-2 border-t border-line px-5 py-3 pb-[max(12px,env(safe-area-inset-bottom))]">
          <button class="btn" @click="emit('close')">关闭</button>
          <button v-if="failed.length" class="btn btn-primary" :disabled="retrying" @click="emit('retry', failed.map((r) => r.id))">{{ retrying ? '重试中…' : `重试失败项（${failed.length}）` }}</button>
        </footer>
      </section>
    </div>
  </Transition>
</template>
