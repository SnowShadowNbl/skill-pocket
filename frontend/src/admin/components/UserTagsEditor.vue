<script setup>
import { computed, ref, watch } from 'vue'
import { api } from '../../api'
import { toast } from '../../composables/toast'
import { TAG_COLOR, loadTags, tagState } from '../composables/useTags'

// 用户详情里的标签：点标签开关，整体保存（最多 20 个）
const props = defineProps({ userId: { type: Number, required: true }, tags: { type: Array, default: () => [] }, canWrite: Boolean })
const emit = defineEmits(['saved'])
const picked = ref(new Set())
const busy = ref(false)
watch(() => [props.userId, props.tags], () => (picked.value = new Set((props.tags || []).map((t) => t.id))), { immediate: true })
loadTags().catch(() => {})
const dirty = computed(() => {
  const a = new Set((props.tags || []).map((t) => t.id))
  return a.size !== picked.value.size || [...a].some((x) => !picked.value.has(x))
})
function toggle(id) {
  const s = new Set(picked.value)
  if (s.has(id)) s.delete(id)
  else s.add(id)
  picked.value = s
}
async function save() {
  busy.value = true
  try {
    const r = await api(`/api/admin/users/${props.userId}/tags`, { method: 'PUT', body: { tag_ids: [...picked.value] } })
    toast('标签已保存', 'success')
    emit('saved', r.tags)
  } catch (e) {
    toast(e.message, 'error')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div>
    <p v-if="!tagState.items.length" class="m-0 text-[13px] text-mute">还没有标签，先在用户列表的「标签」里新建</p>
    <div v-else class="flex flex-wrap items-center gap-1.5">
      <button v-for="t in tagState.items" :key="t.id" type="button" class="tag cursor-pointer border-0 !h-8 !px-3 transition-opacity" :class="[TAG_COLOR[t.color], picked.has(t.id) ? '' : 'opacity-40']" :disabled="!canWrite" :aria-pressed="picked.has(t.id)" @click="toggle(t.id)">{{ t.name }}</button>
      <button v-if="canWrite && dirty" class="btn btn-sm ml-1" :disabled="busy" @click="save">保存标签</button>
    </div>
  </div>
</template>
