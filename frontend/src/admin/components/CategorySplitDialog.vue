<script setup>
import { computed, ref, watch } from 'vue'
import { api, isCancelled } from '../../api'
import { toast } from '../../composables/toast'
import ACheckbox from './ACheckbox.vue'

// 拆分分类：从一个分类里挑出一部分条目，放进同一大类下新建的子分类（迁过去的条目分类会被锁定）。先预览再确认
//   <CategorySplitDialog :open :category="{ id, code, name }" @close @done />
const props = defineProps({ open: Boolean, category: { type: Object, default: null } })
const emit = defineEmits(['close', 'done'])
const items = ref(null)
const page = ref(1)
const picked = ref(new Set())
const name = ref('')
const reason = ref('')
const preview = ref(null)
const busy = ref(false)
const err = ref('')

async function load(more = false) {
  page.value = more ? page.value + 1 : 1
  try {
    const d = await api(`/api/admin/items?category=${props.category.code}&sort=name&size=100&page=${page.value}`)
    items.value = more ? { ...d, items: [...items.value.items, ...d.items] } : d
  } catch (e) {
    if (!isCancelled(e)) err.value = e.message
  }
}
watch(() => [props.open, props.category?.id], () => {
  items.value = null
  picked.value = new Set()
  name.value = ''
  reason.value = ''
  preview.value = null
  err.value = ''
  if (props.open && props.category) load()
})
// 选择或名称变了，预览作废
watch([picked, name], () => { preview.value = null })

const count = computed(() => picked.value.size)
function toggle(id) {
  const s = new Set(picked.value)
  s.has(id) ? s.delete(id) : s.add(id)
  picked.value = s
}
const body = (dry) => ({ reason: reason.value.trim(), dry_run: dry, parts: [{ name: name.value.trim(), item_ids: [...picked.value] }] })
async function check() {
  busy.value = true
  err.value = ''
  try {
    preview.value = await api(`/api/admin/categories/${props.category.id}/split`, { method: 'POST', body: body(true) })
  } catch (e) {
    err.value = e.message
  } finally {
    busy.value = false
  }
}
const canRun = computed(() => preview.value && !preview.value.conflicts?.length && reason.value.trim().length >= 4)
async function run() {
  busy.value = true
  err.value = ''
  try {
    const r = await api(`/api/admin/categories/${props.category.id}/split`, { method: 'POST', body: body(false) })
    toast(`已拆分出「${r.created?.[0]?.name || name.value}」，迁移了 ${count.value} 个条目`, 'success')
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
      <form class="card flex max-h-[92dvh] w-full flex-col overflow-hidden rounded-b-none shadow-[0_20px_50px_-20px_rgba(15,29,51,.35)] sm:max-w-[520px] sm:rounded-b-lg" role="dialog" aria-modal="true" aria-label="拆分分类" @submit.prevent="canRun ? run() : check()">
        <div class="px-5 pt-5 sm:px-6 sm:pt-6">
          <h2 class="m-0 text-base font-semibold">拆分「{{ category.name }}」</h2>
          <p class="m-0 mt-1 text-[13px] text-mute">勾选要拆出去的条目，放进新建的子分类<template v-if="items"> · 已选 {{ count }} / {{ items.total }}</template></p>
        </div>
        <div class="mt-3 min-h-0 flex-1 overflow-y-auto border-y border-line">
          <div v-if="!items" class="p-4"><div class="skeleton h-32" /></div>
          <p v-else-if="!items.items.length" class="empty">这个分类里没有条目</p>
          <ul v-else class="m-0 list-none p-0">
            <li v-for="i in items.items" :key="i.id" class="flex min-h-11 cursor-pointer items-center gap-3 border-b border-line px-5 py-1.5 text-[13px] last:border-0 hover:bg-subtle sm:px-6" @click="toggle(i.id)">
              <ACheckbox :model-value="picked.has(i.id)" label="选择" @update:model-value="toggle(i.id)" />
              <span class="min-w-0 flex-1 truncate">{{ i.name }}</span><span class="shrink-0 text-xs text-mute">{{ i.status_label }}</span>
            </li>
          </ul>
          <button v-if="items && items.items.length < items.total" type="button" class="btn btn-sm m-3" @click="load(true)">加载更多</button>
        </div>
        <div class="px-5 py-4 sm:px-6">
          <input v-model="name" class="input" placeholder="新子分类的名称" maxlength="30" aria-label="新子分类名称" />
          <div v-if="preview" class="mt-3 rounded-lg bg-subtle px-3.5 py-2.5 text-[13px]">
            <p class="m-0">「{{ category.name }}」拆出 <b class="tabular-nums">{{ preview.parts?.[0]?.count }}</b> 个条目到「{{ preview.parts?.[0]?.name }}」，原分类剩 <b class="tabular-nums">{{ preview.remaining_count }}</b> 个</p>
            <p v-for="c in preview.conflicts" :key="c" class="m-0 mt-1.5 text-bad">{{ c }}</p>
          </div>
          <textarea v-if="preview && !preview.conflicts?.length" v-model="reason" class="input mt-3 h-16 resize-none py-2" placeholder="拆分原因（会记入操作日志，至少 4 个字）" maxlength="300" aria-label="原因" />
          <p v-if="err" class="m-0 mt-3 text-[13px] text-bad">{{ err }}</p>
          <div class="mt-4 flex justify-end gap-2">
            <button type="button" class="btn" @click="emit('close')">取消</button>
            <button v-if="!canRun" class="btn btn-primary" :disabled="busy || !count || !name.trim()">{{ busy ? '检查中…' : '预览' }}</button>
            <button v-else class="btn btn-danger" :disabled="busy">{{ busy ? '拆分中…' : '确认拆分' }}</button>
          </div>
        </div>
      </form>
    </div>
  </Transition>
</template>
