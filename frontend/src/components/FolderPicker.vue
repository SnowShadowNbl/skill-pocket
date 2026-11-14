<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { api } from '../api'
import { createFolder, customDims, favTree, foldersByRecent, loadFavTree, setItemFolders } from '../composables/favorites'
import { toast } from '../composables/toast'
import Icon from './Icon.vue'

// 收藏后弹出的小浮层：勾选放进哪些分类，或就地新建一个。不理它 4 秒后自动收起，不打断浏览。
const props = defineProps({
  item: { type: Object, required: true },
  anchor: { type: Object, default: null }, // 触发按钮的 DOM，用来定位
  open: Boolean,
  sticky: Boolean, // 主动打开时不自动收起
})
const emit = defineEmits(['close', 'change'])

const panel = ref(null)
const dimId = ref(null)
const selected = ref(new Set())
const newName = ref('')
const adding = ref(false)
const pos = ref({})
let timer

const dims = computed(() => customDims())
const dim = computed(() => dims.value.find((d) => d.id === dimId.value) || dims.value[0])
const folders = computed(() => foldersByRecent(dim.value).slice(0, 12))
const more = computed(() => (dim.value?.folders.length || 0) - folders.value.length)

function place() {
  const r = props.anchor?.getBoundingClientRect()
  if (!r) return
  const w = Math.min(300, innerWidth - 24)
  const left = Math.max(12, Math.min(r.right - w, innerWidth - w - 12))
  const below = r.bottom + 8
  const top = below + 260 > innerHeight ? Math.max(12, r.top - 8 - 260) : below
  pos.value = { left: `${left}px`, top: `${top}px`, width: `${w}px` }
}

function arm() {
  clearTimeout(timer)
  if (!props.sticky) timer = setTimeout(() => emit('close'), 4000)
}
function hold() {
  clearTimeout(timer)
}

async function loadCurrent() {
  try {
    const d = await api(`/api/items/${props.item.id}`)
    selected.value = new Set(d.favorite?.folder_ids || [])
  } catch {}
}

watch(
  () => props.open,
  async (v) => {
    if (!v) return clearTimeout(timer)
    if (!favTree.data) await loadFavTree()
    dimId.value = dims.value[0]?.id ?? null
    await loadCurrent()
    await nextTick()
    place()
    arm()
  },
  { immediate: true },
)

async function save(ids) {
  try {
    const got = await setItemFolders(props.item.id, dim.value.id, ids)
    selected.value = new Set(got)
    emit('change', got)
  } catch (e) {
    toast(e.message, 'error')
  }
}

function inDim(ids) {
  const own = new Set(dim.value.folders.map((x) => x.id))
  return [...ids].filter((id) => own.has(id))
}

function toggle(f) {
  hold()
  const ids = inDim(selected.value)
  save(ids.includes(f.id) ? ids.filter((x) => x !== f.id) : [...ids, f.id])
}

async function addFolder() {
  const name = newName.value.trim()
  if (!name) return
  adding.value = true
  try {
    const f = await createFolder(dim.value.id, name)
    newName.value = ''
    await save([...inDim(selected.value), f.id])
  } catch (e) {
    toast(e.message, 'error')
  } finally {
    adding.value = false
  }
}

function onDocDown(e) {
  if (props.open && panel.value && !panel.value.contains(e.target) && !props.anchor?.contains(e.target)) emit('close')
}
function onKey(e) {
  if (e.key === 'Escape' && props.open) emit('close')
}
addEventListener('pointerdown', onDocDown, true)
addEventListener('keydown', onKey)
addEventListener('resize', place)
onBeforeUnmount(() => {
  clearTimeout(timer)
  removeEventListener('pointerdown', onDocDown, true)
  removeEventListener('keydown', onKey)
  removeEventListener('resize', place)
})
</script>

<template>
  <Teleport to="body">
    <Transition name="pop">
      <div
        v-if="open && dim"
        ref="panel"
        class="glass-strong fixed z-[70] rounded-2xl p-3 shadow-[0_18px_40px_-16px_rgb(11_47_122/0.55)]"
        :style="pos"
        role="dialog"
        aria-label="放进分类"
        @pointerenter="hold"
        @pointerleave="arm"
        @focusin="hold"
        @click.stop
      >
        <div class="flex items-center gap-1.5 text-[13px]">
          <Icon name="check" :size="14" class="text-ok" />
          <span class="font-semibold">已收藏</span>
          <span class="text-mute">· 放进</span>
          <span class="font-medium text-brand">{{ dim.name }}</span>
        </div>
        <div v-if="dims.length > 1" class="scrollbar-none -mx-1 mt-2 flex gap-1 overflow-x-auto px-1" role="tablist" aria-label="选择维度">
          <button
            v-for="d in dims"
            :key="d.id"
            type="button"
            role="tab"
            :aria-selected="d.id === dim.id"
            class="h-7 shrink-0 cursor-pointer rounded-full px-2.5 text-[12px] transition-colors"
            :class="d.id === dim.id ? 'bg-ink font-medium text-white' : 'bg-ink/[0.05] text-ink-2 hover:bg-ink/10'"
            @click="(dimId = d.id), hold()"
          >{{ d.name }}</button>
        </div>

        <div class="mt-2.5 flex max-h-40 flex-wrap gap-1.5 overflow-y-auto">
          <button
            v-for="f in folders"
            :key="f.id"
            type="button"
            class="flex h-8 cursor-pointer items-center gap-1 rounded-full px-3 text-[13px] transition-all duration-200"
            :class="selected.has(f.id) ? 'bg-brand text-white' : 'border border-edge bg-white/70 text-ink-2 hover:bg-white'"
            :aria-pressed="selected.has(f.id)"
            @click="toggle(f)"
          >
            <span v-if="f.emoji">{{ f.emoji }}</span>{{ f.name }}
          </button>
          <span v-if="!folders.length" class="py-1 text-[12.5px] text-mute">还没有分类，新建一个吧</span>
          <RouterLink v-if="more > 0" to="/pocket" class="flex h-8 items-center px-2 text-[12.5px] text-brand">还有 {{ more }} 个…</RouterLink>
        </div>

        <form class="mt-2.5 flex gap-1.5" @submit.prevent="addFolder">
          <input
            v-model="newName"
            class="field h-9 min-w-0 flex-1 text-[13px] sm:h-9"
            maxlength="20"
            placeholder="新建分类，回车添加"
            aria-label="新建分类名称"
            @focus="hold"
          />
          <button class="btn-glass btn-sm shrink-0" :disabled="adding || !newName.trim()" aria-label="新建分类"><Icon name="folder-plus" :size="15" /></button>
        </form>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.pop-enter-active,
.pop-leave-active {
  transition: opacity 0.22s ease, transform 0.32s cubic-bezier(0.16, 1, 0.3, 1);
}
.pop-enter-from,
.pop-leave-to {
  opacity: 0;
  transform: translateY(-6px) scale(0.97);
}
@media (prefers-reduced-motion: reduce) {
  .pop-enter-active,
  .pop-leave-active {
    transition: opacity 0.15s ease;
  }
}
</style>
