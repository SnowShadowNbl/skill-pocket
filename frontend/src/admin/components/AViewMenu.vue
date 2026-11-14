<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api, isCancelled } from '../../api'
import Icon from '../../components/Icon.vue'
import { confirmDialog, promptDialog } from '../../composables/dialog'
import { toast } from '../../composables/toast'

// 保存的筛选视图（按管理员个人，存在后端）：选一个视图就把条件整体应用到筛选栏；可另存为、更新、重命名、删除。
//   <AViewMenu scope="users" :query="query" @apply="apply" />
//   接口：GET /api/admin/views?scope= / POST /api/admin/views / PUT、DELETE /api/admin/views/{id}
const props = defineProps({ scope: { type: String, required: true }, query: { type: Object, required: true } })
const emit = defineEmits(['apply'])
const open = ref(false)
const views = ref(null)
const selectedId = ref(null)
const root = ref(null)
const busy = ref(false)
const max = ref(20)

const sig = (q) => JSON.stringify(Object.entries(q || {}).sort())
const selected = computed(() => views.value?.find((v) => v.id === selectedId.value) || null)
const dirty = computed(() => !!selected.value && sig(selected.value.query) !== sig(props.query))
const hasQuery = computed(() => Object.keys(props.query).length > 0)
// 当前条件正好等于某个视图时，按钮上显示它的名字
const matched = computed(() => views.value?.find((v) => sig(v.query) === sig(props.query)) || null)
const title = computed(() => matched.value?.name || (selected.value && dirty.value ? `${selected.value.name}（已修改）` : '视图'))

async function load() {
  try {
    const d = await api(`/api/admin/views?scope=${props.scope}`)
    views.value = d.items
    max.value = d.max || 20
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
    views.value = []
  }
}
function toggle() {
  open.value = !open.value
  if (open.value && !views.value) load()
}
function pick(v) {
  selectedId.value = v.id
  emit('apply', v.query)
  open.value = false
}
async function guard(fn) {
  busy.value = true
  try {
    await fn()
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  } finally {
    busy.value = false
  }
}
async function saveAs() {
  const name = await promptDialog({ title: '另存为视图', placeholder: '视图名称，例如：纯微信 · 小程序', maxlength: 30, required: true, okText: '保存' })
  if (!name) return
  await guard(async () => {
    const v = await api('/api/admin/views', { method: 'POST', body: { scope: props.scope, name, query: props.query } })
    views.value = [...(views.value || []), v]
    selectedId.value = v.id
    toast(`已保存视图「${name}」`, 'success')
  })
}
async function update() {
  const v = selected.value
  await guard(async () => {
    const n = await api(`/api/admin/views/${v.id}`, { method: 'PUT', body: { query: props.query } })
    views.value = views.value.map((x) => (x.id === v.id ? { ...x, ...n } : x))
    toast(`已更新视图「${v.name}」`, 'success')
  })
}
async function rename(v) {
  const name = await promptDialog({ title: '重命名视图', value: v.name, maxlength: 30, required: true, okText: '保存' })
  if (!name || name === v.name) return
  await guard(async () => {
    const n = await api(`/api/admin/views/${v.id}`, { method: 'PUT', body: { name } })
    views.value = views.value.map((x) => (x.id === v.id ? { ...x, ...n } : x))
  })
}
async function remove(v) {
  if (!(await confirmDialog({ title: `删除视图「${v.name}」？`, okText: '删除', danger: true }))) return
  await guard(async () => {
    await api(`/api/admin/views/${v.id}`, { method: 'DELETE' })
    views.value = views.value.filter((x) => x.id !== v.id)
    if (selectedId.value === v.id) selectedId.value = null
  })
}

const outside = (e) => root.value && !root.value.contains(e.target) && (open.value = false)
onMounted(() => document.addEventListener('pointerdown', outside))
onBeforeUnmount(() => document.removeEventListener('pointerdown', outside))
</script>

<template>
  <div ref="root" class="relative">
    <button type="button" class="input flex items-center gap-2 text-left sm:w-auto sm:min-w-[110px]" :class="{ '!border-primary': open || matched }" aria-haspopup="menu" :aria-expanded="open" @click="toggle">
      <Icon name="layers" :size="15" class="shrink-0 text-mute" /><span class="min-w-0 flex-1 truncate" :class="matched ? 'font-medium text-primary' : ''">{{ title }}</span>
      <Icon name="chevron-down" :size="15" class="shrink-0 text-mute transition-transform" :class="{ 'rotate-180': open }" />
    </button>
    <Transition name="fade">
      <div v-if="open" class="absolute top-full left-0 z-30 mt-1 w-full min-w-64 rounded-lg border border-line bg-white p-1 shadow-[0_8px_24px_-8px_rgba(15,29,51,.2)]" role="menu">
        <div v-if="!views" class="skeleton m-1 h-16" />
        <p v-else-if="!views.length" class="px-2.5 py-3 text-[13px] text-mute">还没有保存的视图</p>
        <ul v-else class="m-0 max-h-64 list-none overflow-y-auto p-0">
          <li v-for="v in views" :key="v.id" class="group flex items-center rounded-md" :class="v.id === selectedId ? 'bg-primary-soft' : 'hover:bg-subtle'">
            <button class="min-h-10 min-w-0 flex-1 truncate px-2.5 text-left text-[13px]" :class="v.id === selectedId ? 'font-semibold text-primary' : ''" role="menuitem" @click="pick(v)">{{ v.name }}</button>
            <button class="grid h-10 w-9 shrink-0 place-items-center text-mute hover:text-primary" aria-label="重命名" @click="rename(v)"><Icon name="pencil" :size="13" /></button>
            <button class="grid h-10 w-9 shrink-0 place-items-center text-mute hover:text-bad" aria-label="删除" @click="remove(v)"><Icon name="trash" :size="13" /></button>
          </li>
        </ul>
        <div class="mt-1 flex flex-col gap-1 border-t border-line p-1">
          <button v-if="dirty" class="btn justify-start" :disabled="busy" @click="update"><Icon name="refresh" :size="14" />用当前条件更新「{{ selected.name }}」</button>
          <button v-if="!views || views.length < max" class="btn justify-start" :disabled="busy || !hasQuery" @click="saveAs"><Icon name="plus" :size="14" />另存为视图</button>
        </div>
      </div>
    </Transition>
  </div>
</template>
