<script setup>
import { computed, ref, watch } from 'vue'
import { api } from '../../api'
import Icon from '../../components/Icon.vue'
import { toast } from '../../composables/toast'
import { askReason } from '../composables/reason'
import { COLOR_NAME, TAG_COLOR, TAG_DOT, loadTags, tagState } from '../composables/useTags'
import ADrawer from './ADrawer.vue'

// 标签管理：新建、改名改颜色、删除（会同时去掉所有用户身上的这个标签）
const props = defineProps({ open: Boolean, canWrite: Boolean })
const emit = defineEmits(['close', 'changed'])
const form = ref({ id: null, name: '', color: 'blue', description: '' })
const busy = ref(false)
const editing = computed(() => form.value.id != null)

watch(() => props.open, (v) => {
  if (v) loadTags(true).catch((e) => toast(e.message, 'error'))
})
const reset = () => (form.value = { id: null, name: '', color: 'blue', description: '' })
const edit = (t) => (form.value = { id: t.id, name: t.name, color: t.color, description: t.description || '' })

async function save() {
  const f = form.value
  if (!f.name.trim()) return
  busy.value = true
  try {
    const body = { name: f.name.trim(), color: f.color, description: f.description.trim() }
    await api(editing.value ? `/api/admin/tags/${f.id}` : '/api/admin/tags', { method: editing.value ? 'PUT' : 'POST', body })
    toast(editing.value ? '已保存' : '已新建', 'success')
    reset()
    await loadTags(true)
    emit('changed')
  } catch (e) {
    toast(e.code === 'duplicate' ? '已经有同名的标签' : e.code === 'bad_color' ? '颜色不对' : e.message, 'error')
  } finally {
    busy.value = false
  }
}
async function remove(t) {
  const reason = await askReason({ title: `删除标签「${t.name}」`, impact: `${t.users} 位用户身上的这个标签会一并去掉，不能恢复`, templates: ['不再使用', '标签重复，合并到别的标签'], danger: true, okText: '删除' })
  if (reason === null) return
  try {
    await api(`/api/admin/tags/${t.id}`, { method: 'DELETE', body: { reason } })
    toast('已删除', 'success')
    if (form.value.id === t.id) reset()
    await loadTags(true)
    emit('changed')
  } catch (e) {
    toast(e.message, 'error')
  }
}
</script>

<template>
  <ADrawer :open="open" label="标签管理" :width="480" @close="emit('close')">
    <template #header><h2 class="m-0 text-base font-semibold">标签管理</h2></template>
    <form v-if="canWrite" class="rounded-lg bg-subtle p-3.5" @submit.prevent="save">
      <p class="m-0 mb-2 text-[13px] font-semibold">{{ editing ? '修改标签' : '新建标签' }}</p>
      <input v-model="form.name" class="input" maxlength="30" placeholder="标签名，例如：内测用户" aria-label="标签名" />
      <div class="mt-2.5 flex flex-wrap items-center gap-2" role="radiogroup" aria-label="颜色">
        <button v-for="c in tagState.colors" :key="c" type="button" role="radio" :aria-checked="form.color === c" :aria-label="COLOR_NAME[c] || c" class="grid h-10 w-10 cursor-pointer place-items-center rounded-full border-2 bg-transparent p-0" :class="form.color === c ? 'border-ink' : 'border-transparent'" @click="form.color = c"><i class="h-5 w-5 rounded-full" :class="TAG_DOT[c]" /></button>
      </div>
      <input v-model="form.description" class="input mt-2.5" maxlength="100" placeholder="说明（可选）" aria-label="说明" />
      <div class="mt-3 flex gap-2">
        <button class="btn btn-primary" :disabled="busy || !form.name.trim()">{{ editing ? '保存' : '新建' }}</button>
        <button v-if="editing" type="button" class="btn" @click="reset">取消</button>
      </div>
    </form>
    <p v-if="!tagState.items.length" class="m-0 mt-4 text-center text-[13px] text-mute">还没有标签</p>
    <ul class="m-0 mt-3 list-none p-0">
      <li v-for="t in tagState.items" :key="t.id" class="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-line py-2.5 last:border-0">
        <span class="tag" :class="TAG_COLOR[t.color]">{{ t.name }}</span>
        <span class="min-w-0 flex-1 text-xs break-words text-mute">{{ t.users }} 人<template v-if="t.description"> · {{ t.description }}</template></span>
        <span v-if="canWrite" class="flex gap-1.5"><button class="btn btn-sm" @click="edit(t)">编辑</button><button class="btn btn-sm btn-danger" :aria-label="`删除标签${t.name}`" @click="remove(t)"><Icon name="trash" :size="14" /></button></span>
      </li>
    </ul>
  </ADrawer>
</template>
