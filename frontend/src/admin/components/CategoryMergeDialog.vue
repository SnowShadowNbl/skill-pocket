<script setup>
import { computed, ref, watch } from 'vue'
import { api } from '../../api'
import Icon from '../../components/Icon.vue'
import { toast } from '../../composables/toast'
import ASelect from './ASelect.vue'

// 合并分类：把「源分类」的所有条目迁到目标分类，源分类停用并指向目标。先选目标看预览，再填原因确认
//   <CategoryMergeDialog :open :category="{ id, name }" :options="[{ value, label, group }]" @close @done />
const props = defineProps({ open: Boolean, category: { type: Object, default: null }, options: { type: Array, default: () => [] } })
const emit = defineEmits(['close', 'done'])
const target = ref('')
const preview = ref(null)
const reason = ref('')
const busy = ref(false)
const err = ref('')

watch(() => [props.open, props.category?.id], () => {
  target.value = ''
  preview.value = null
  reason.value = ''
  err.value = ''
})
const choices = computed(() => [{ value: '', label: '选择目标分类…' }, ...props.options.filter((o) => o.value !== props.category?.id)])

watch(target, async (t) => {
  preview.value = null
  err.value = ''
  if (!t) return
  try {
    preview.value = await api(`/api/admin/categories/${props.category.id}/merge`, { method: 'POST', body: { target_id: t, reason: '', dry_run: true } })
  } catch (e) {
    err.value = e.message
  }
})
const ok = computed(() => preview.value && !preview.value.conflicts?.length && reason.value.trim().length >= 4)

async function run() {
  busy.value = true
  err.value = ''
  try {
    const r = await api(`/api/admin/categories/${props.category.id}/merge`, { method: 'POST', body: { target_id: target.value, reason: reason.value.trim(), dry_run: false } })
    toast(`已合并，迁移了 ${r.moved_count} 个条目`, 'success')
    emit('done')
    emit('close')
  } catch (e) {
    err.value = e.message
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <Transition name="fade">
    <div v-if="open && category" class="fixed inset-0 z-50 grid place-items-end bg-ink/35 sm:place-items-center sm:px-4" @click.self="emit('close')" @keydown.esc="emit('close')">
      <form class="card max-h-dvh w-full overflow-y-auto rounded-b-none p-5 shadow-[0_20px_50px_-20px_rgba(15,29,51,.35)] sm:max-w-[480px] sm:rounded-b-lg sm:p-6" role="dialog" aria-modal="true" aria-label="合并分类" @submit.prevent="ok && run()">
        <h2 class="m-0 text-base font-semibold">合并「{{ category.name }}」到…</h2>
        <div class="mt-4"><ASelect v-model="target" :options="choices" label="目标分类" searchable /></div>
        <div v-if="preview" class="mt-4 rounded-lg bg-subtle px-3.5 py-3 text-[13px]">
          <p class="m-0">将迁移 <b class="tabular-nums">{{ preview.moved_count }}</b> 个条目到「{{ preview.target?.name }}」<template v-if="preview.locked_count">，其中 {{ preview.locked_count }} 个的分类是人工设置的（迁移后仍保持锁定）</template></p>
          <p v-if="preview.sample?.length" class="m-0 mt-1.5 text-xs text-mute">例如：{{ preview.sample.join('、') }}</p>
          <p v-for="c in preview.conflicts" :key="c" class="m-0 mt-2 flex items-start gap-1.5 text-bad"><Icon name="alert" :size="14" class="mt-0.5 shrink-0" />{{ c }}</p>
          <p class="m-0 mt-2 text-xs text-mute">「{{ category.name }}」会被停用，用它的旧编码筛选时自动改看目标分类；榜单立即重算。</p>
        </div>
        <textarea v-if="preview && !preview.conflicts?.length" v-model="reason" class="input mt-3 h-20 resize-none py-2" placeholder="合并原因（会记入操作日志，至少 4 个字）" maxlength="300" aria-label="原因" />
        <p v-if="err" class="m-0 mt-3 text-[13px] text-bad">{{ err }}</p>
        <div class="mt-5 flex justify-end gap-2">
          <button type="button" class="btn" @click="emit('close')">取消</button>
          <button class="btn btn-danger" :disabled="!ok || busy">{{ busy ? '合并中…' : '确认合并' }}</button>
        </div>
      </form>
    </div>
  </Transition>
</template>
