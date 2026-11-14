<script setup>
import CheckBox from '../components/CheckBox.vue'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'
import { api, authHeaders } from '../api'
import AiTag from '../components/AiTag.vue'
import AppSelect from '../components/AppSelect.vue'
import Icon from '../components/Icon.vue'
import ItemCard from '../components/ItemCard.vue'
import CompareModeToggle from '../components/CompareModeToggle.vue'
import { favState, favTree, loadFavTree } from '../composables/favorites'
import { authState, requireLogin } from '../composables/auth'
import { confirmDialog, promptDialog } from '../composables/dialog'
import { toast } from '../composables/toast'

const route = useRoute()
const router = useRouter()

const SORTS = [
  { value: 'favorited', label: '按收藏时间' },
  { value: 'stars', label: '按星标' },
  { value: 'collected', label: '按收录时间' },
]
const EMOJIS = ['📌', '⭐', '🔥', '💼', '🧪', '📝', '🎨', '🎙️', '🤖', '📚', '🛠️', '💡']

// ---------------------------------------------------------------- 当前视图（存在 URL 里，刷新 / 分享不丢）
const dimKey = computed(() => route.query.dim || '') // group / kind / 自定义维度 id
const folderKey = computed(() => route.query.folder || '') // 空=全部，none=未整理
const keyword = ref(route.query.q || '')
const sort = computed(() => route.query.sort || 'favorited')

const tree = computed(() => favTree.data)
const dims = computed(() => tree.value?.dimensions || [])
const systemDims = computed(() => tree.value?.system || [])
const currentDim = computed(() => {
  const k = dimKey.value || String(dims.value[0]?.id ?? 'group')
  return systemDims.value.find((d) => d.key === k) || dims.value.find((d) => String(d.id) === k) || systemDims.value[0]
})
const isCustom = computed(() => currentDim.value && !currentDim.value.system)
const currentFolder = computed(() => {
  if (!currentDim.value || !folderKey.value || folderKey.value === 'none') return null
  return currentDim.value.folders.find((f) => String(f.id ?? f.key) === folderKey.value) || null
})
const title = computed(() => (folderKey.value === 'none' ? '未整理' : currentFolder.value ? currentFolder.value.name : '全部收藏'))

// 嵌在「口袋 → 我的收藏」里时（embedded），筛选条件放在口袋页的地址里，详情抽屉由口袋页负责打开
const props = defineProps({ embedded: Boolean, basePath: { type: String, default: '' } })
// v3.2：收藏搬进「口袋」页（/pocket），嵌入时由外层传入地址
const base = computed(() => props.basePath || (props.embedded ? '/me' : '/favorites'))

function go(patch) {
  const q = { ...route.query, ...patch }
  for (const k of Object.keys(q)) if (!q[k] || (k === 'sort' && q[k] === 'favorited')) delete q[k]
  if (props.embedded) q.tab = 'favorites'
  router.replace({ path: base.value, query: q })
}
function pickDim(d) {
  go({ dim: d.system ? d.key : String(d.id), folder: '' })
}
function pickFolder(key) {
  go({ dim: currentDim.value.system ? currentDim.value.key : String(currentDim.value.id), folder: key })
}

// ---------------------------------------------------------------- 列表
const items = ref([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)

function params() {
  const p = { fav: '1', sort: sort.value, q: route.query.q || '', page: page.value, size: 24 }
  const d = currentDim.value
  if (!d) return p
  const f = folderKey.value
  if (d.system && f) p[d.key === 'group' ? 'category' : 'kind'] = f
  if (!d.system && f === 'none') Object.assign(p, { fav_folder: 'none', fav_dim: d.id })
  else if (!d.system && f) p.fav_folder = f
  return p
}

async function load(reset = true) {
  if (reset) page.value = 1
  loading.value = true
  try {
    const data = await api(`/api/items?${new URLSearchParams(params())}`)
    items.value = reset ? data.items : [...items.value, ...data.items]
    total.value = data.total
  } catch (e) {
    toast(e.message, 'error')
  } finally {
    loading.value = false
  }
}
function more() {
  page.value++
  load(false)
}

const refresh = () => Promise.all([loadFavTree(), load()])

// ---- v3.3 分享收藏分类 / 导出收藏 ----
async function copyText(t) {
  try {
    await navigator.clipboard.writeText(t)
    return true
  } catch {
    return false
  }
}
async function shareFolder(f) {
  menuFor.value = null
  try {
    const r = await api(`/api/favorites/folders/${f.id}/share`, { method: 'POST' })
    f.share_token = r.token
    const url = location.origin + r.path
    toast((await copyText(url)) ? `已复制分享链接：${url}` : `分享链接：${url}`, 'success', 4000)
  } catch (e) {
    toast(e.message, 'error')
  }
}
async function unshareFolder(f) {
  menuFor.value = null
  if (!(await confirmDialog({ title: `停止分享「${f.name}」？`, message: '之前发出去的链接会立即失效。', okText: '停止分享' }))) return
  try {
    await api(`/api/favorites/folders/${f.id}/share`, { method: 'DELETE' })
    f.share_token = null
    toast('已停止分享', 'success')
  } catch (e) {
    toast(e.message, 'error')
  }
}
const exportOpen = ref(false)
async function exportFavs(fmt) {
  exportOpen.value = false
  try {
    const res = await fetch(`/api/favorites/export?format=${fmt}`, { headers: authHeaders() })
    if (!res.ok) throw new Error(`导出失败（${res.status}）`)
    const blob = await res.blob()
    const name = decodeURIComponent((res.headers.get('content-disposition') || '').split("''")[1] || `skill-pocket.${fmt}`)
    const a = Object.assign(document.createElement('a'), { href: URL.createObjectURL(blob), download: name })
    a.click()
    setTimeout(() => URL.revokeObjectURL(a.href), 2000)
    toast('已导出', 'success')
  } catch (e) {
    toast(e.message, 'error')
  }
}
watch(() => [route.query.dim, route.query.folder, route.query.q, route.query.sort], () => route.path === base.value && load())
// 取消收藏（卡片上或详情里）后移出列表
watch(
  () => ({ ...favState.map }),
  (map) => {
    const before = items.value.length
    items.value = items.value.filter((x) => map[x.id] !== false)
    if (before !== items.value.length) {
      total.value -= before - items.value.length
      loadFavTree()
    }
  },
)
// 从详情抽屉回来时刷新（可能在里面调整了分类）
watch(() => route.path, (p, old) => p === base.value && old?.startsWith(`${base.value}/items`) && refresh())

let qTimer
watch(keyword, (v) => {
  clearTimeout(qTimer)
  qTimer = setTimeout(() => go({ q: v.trim() }), 300)
})

// ---------------------------------------------------------------- 多选与批量操作
const selecting = ref(false)
const selected = ref(new Set())
const moveMenu = ref(false)

function toggleSelect(it) {
  const s = new Set(selected.value)
  s.has(it.id) ? s.delete(it.id) : s.add(it.id)
  selected.value = s
}
function exitSelect() {
  selecting.value = false
  selected.value = new Set()
  moveMenu.value = false
}
function selectAll() {
  selected.value = selected.value.size === items.value.length ? new Set() : new Set(items.value.map((x) => x.id))
}

// 长按进入多选（手机）；长按松手后紧跟的那次 click 要吞掉，否则会立刻取消选中
let pressTimer
let pressed = false
function pressStart(e, it) {
  if (e.pointerType === 'mouse') return
  clearTimeout(pressTimer)
  pressTimer = setTimeout(() => {
    pressed = true
    if (!selecting.value) selecting.value = true
    toggleSelect(it)
    navigator.vibrate?.(12)
  }, 480)
}
const pressEnd = () => clearTimeout(pressTimer)
function onCardClick(e, it) {
  if (!selecting.value && !pressed) return
  e.preventDefault()
  e.stopPropagation()
  if (pressed) pressed = false
  else toggleSelect(it)
}

async function moveTo(folderIds, remove = []) {
  const ids = [...selected.value]
  if (!ids.length) return
  try {
    await api('/api/favorites/move', { method: 'POST', body: { item_ids: ids, add: folderIds, remove } })
    toast(remove.length ? `已移出 ${ids.length} 个` : `已放进分类（${ids.length} 个）`, 'success', 1600)
    exitSelect()
    refresh()
  } catch (e) {
    toast(e.message, 'error')
  }
}

async function unfavSelected() {
  const ids = [...selected.value]
  if (!ids.length || !(await confirmDialog({ title: `取消收藏这 ${ids.length} 个条目？`, message: '可以在提示条里撤销。', danger: true, okText: '取消收藏' }))) return
  await Promise.all(ids.map((id) => api(`/api/items/${id}/favorite`, { method: 'POST', body: { on: false } }).catch(() => null)))
  ids.forEach((id) => (favState.map[id] = false))
  showUndo(`已取消收藏 ${ids.length} 个`, async () => {
    await Promise.all(ids.map((id) => api(`/api/items/${id}/favorite`, { method: 'POST', body: { on: true } })))
    ids.forEach((id) => (favState.map[id] = true))
    refresh()
  })
  exitSelect()
}

// ---------------------------------------------------------------- 拖拽（电脑端）：卡片拖到左侧分类
const dragItem = ref(null)
const dropTarget = ref(null)
function onCardDragStart(e, it) {
  const ids = selecting.value && selected.value.has(it.id) ? [...selected.value] : [it.id]
  dragItem.value = ids
  e.dataTransfer.effectAllowed = 'copy'
  e.dataTransfer.setData('text/plain', ids.join(','))
}
async function onFolderDrop(f) {
  dropTarget.value = null
  const ids = dragItem.value
  dragItem.value = null
  if (ids && f) {
    selected.value = new Set(ids)
    await moveTo([f.id])
  }
}

// 分类拖动排序
const dragFolder = ref(null)
async function onFolderReorder(target) {
  const d = currentDim.value
  if (!dragFolder.value || dragFolder.value === target || !d || d.system) return
  const list = d.folders.map((f) => f.id).filter((id) => id !== dragFolder.value.id)
  list.splice(list.indexOf(target.id), 0, dragFolder.value.id)
  dragFolder.value = null
  d.folders.sort((a, b) => list.indexOf(a.id) - list.indexOf(b.id))
  try {
    await api('/api/favorites/folders/reorder', { method: 'POST', body: { ids: list } })
  } catch (e) {
    toast(e.message, 'error')
    loadFavTree()
  }
}

// ---------------------------------------------------------------- 分类与维度的增删改
const newFolder = ref('')
const editing = ref(null) // {id, name}
const menuFor = ref(null)

async function addFolder() {
  const name = newFolder.value.trim()
  if (!name || !isCustom.value) return
  try {
    await api('/api/favorites/folders', { method: 'POST', body: { dimension_id: currentDim.value.id, name } })
    newFolder.value = ''
    await loadFavTree()
  } catch (e) {
    toast(e.message, 'error')
  }
}

async function renameCurrent() {
  const f = currentFolder.value
  const name = await promptDialog({ title: '重命名分类', value: f.name, maxlength: 20 })
  if (!name || name === f.name) return
  editing.value = { id: f.id, name }
  renameFolder()
}

async function renameFolder() {
  const e = editing.value
  editing.value = null
  if (!e || !e.name.trim()) return
  try {
    await api(`/api/favorites/folders/${e.id}`, { method: 'PATCH', body: { name: e.name } })
    loadFavTree()
  } catch (err) {
    toast(err.message, 'error')
  }
}

async function setEmoji(f, emoji) {
  menuFor.value = null
  try {
    await api(`/api/favorites/folders/${f.id}`, { method: 'PATCH', body: { emoji: f.emoji === emoji ? '' : emoji } })
    loadFavTree()
  } catch (e) {
    toast(e.message, 'error')
  }
}

async function deleteFolder(f) {
  menuFor.value = null
  try {
    const snap = await api(`/api/favorites/folders/${f.id}`, { method: 'DELETE' })
    if (folderKey.value === String(f.id)) go({ folder: '' })
    await refresh()
    showUndo(`已删除分类「${f.name}」，里面的 ${snap.item_ids.length} 个收藏回到未整理`, async () => {
      await api('/api/favorites/folders', { method: 'POST', body: snap })
      refresh()
    })
  } catch (e) {
    toast(e.message, 'error')
  }
}

async function addDimension() {
  const name = await promptDialog({ title: '新建维度', message: '从另一个角度整理收藏，例如「工作项目」「试用进度」', placeholder: '维度名称', maxlength: 20, icon: 'layers' })
  if (!name) return
  try {
    const d = await api('/api/favorites/dimensions', { method: 'POST', body: { name } })
    await loadFavTree()
    go({ dim: String(d.id), folder: '' })
  } catch (e) {
    toast(e.message, 'error')
  }
}

async function renameDimension() {
  const d = currentDim.value
  const name = await promptDialog({ title: '重命名维度', value: d.name, maxlength: 20, icon: 'layers' })
  if (!name || name === d.name) return
  try {
    await api(`/api/favorites/dimensions/${d.id}`, { method: 'PATCH', body: { name } })
    loadFavTree()
  } catch (e) {
    toast(e.message, 'error')
  }
}

async function deleteDimension() {
  const d = currentDim.value
  const ok = await confirmDialog({
    title: `删除维度「${d.name}」？`,
    message: `它下面的 ${d.folders.length} 个分类会一起删除；只删除分类关系，收藏本身不会被取消。`,
    danger: true,
    okText: '删除维度',
  })
  if (!ok) return
  try {
    await api(`/api/favorites/dimensions/${d.id}`, { method: 'DELETE' })
    go({ dim: '', folder: '' })
    loadFavTree()
  } catch (e) {
    toast(e.message, 'error')
  }
}

// ---------------------------------------------------------------- AI 帮我整理
const organizing = ref(false)
const suggestions = ref(null) // [{item_id, item_name, folder_ids, new_folder, on}]

async function organize() {
  if (!isCustom.value) return
  organizing.value = true
  try {
    const r = await api('/api/favorites/organize/suggest', { method: 'POST', body: { dimension_id: currentDim.value.id } })
    suggestions.value = r.suggestions.map((s) => ({ ...s, on: true }))
    if (!r.suggestions.length) toast('没有需要整理的，或 AI 没找到合适的分类', 'info', 2500)
  } catch (e) {
    toast(e.message, 'error')
  } finally {
    organizing.value = false
  }
}

const folderName = (id) => currentDim.value?.folders.find((f) => f.id === id)?.name || ''

async function applySuggestions() {
  const picked = suggestions.value.filter((s) => s.on)
  suggestions.value = null
  if (!picked.length) return
  try {
    // 先建好建议的新分类，再按分类分组批量放入
    const created = {}
    for (const s of picked) {
      if (s.new_folder && !created[s.new_folder]) {
        const exist = currentDim.value.folders.find((f) => f.name === s.new_folder)
        created[s.new_folder] = exist
          ? exist.id
          : (await api('/api/favorites/folders', { method: 'POST', body: { dimension_id: currentDim.value.id, name: s.new_folder } })).id
      }
    }
    const byFolder = {}
    for (const s of picked) {
      for (const fid of [...s.folder_ids, ...(s.new_folder ? [created[s.new_folder]] : [])]) (byFolder[fid] ||= []).push(s.item_id)
    }
    for (const [fid, ids] of Object.entries(byFolder)) {
      await api('/api/favorites/move', { method: 'POST', body: { item_ids: ids, add: [Number(fid)] } })
    }
    toast(`已整理 ${picked.length} 个收藏`, 'success')
    refresh()
  } catch (e) {
    toast(e.message, 'error')
    refresh()
  }
}

// ---------------------------------------------------------------- 撤销条
const undo = ref(null)
let undoTimer
function showUndo(message, fn) {
  clearTimeout(undoTimer)
  undo.value = { message, fn }
  undoTimer = setTimeout(() => (undo.value = null), 6000)
}
async function runUndo() {
  const u = undo.value
  undo.value = null
  try {
    await u?.fn()
    toast('已撤销', 'success', 1200)
  } catch (e) {
    toast(e.message, 'error')
  }
}

function onKey(e) {
  if (e.key === 'Escape' && selecting.value && !route.params.id) exitSelect()
}

onMounted(() => addEventListener('keydown', onKey))
// 登录后（或换账号）加载自己的收藏；未登录先提示登录
watch(
  () => [authState.ready, authState.version],
  async () => {
    if (!authState.ready) return
    if (!authState.user) {
      items.value = []
      favTree.data = null
      requireLogin('收藏是每个人自己的，登录后就能整理')
      return
    }
    await loadFavTree()
    load()
  },
  { immediate: true },
)
onBeforeUnmount(() => {
  removeEventListener('keydown', onKey)
  clearTimeout(undoTimer)
})
</script>

<template>
  <div>
    <section class="flex flex-wrap items-end gap-3">
      <div v-if="!embedded" class="min-w-0 flex-1">
        <h1 class="text-[clamp(24px,4.6vw,34px)] font-extrabold tracking-tight">
          我的<span class="text-gradient">收藏</span>
        </h1>
        <p class="mt-1 text-sm text-ink-2">收藏后随时整理；按领域、使用类型自动归组，也可以建自己的分类</p>
      </div>
      <!-- 搜索 + v3.3 导出：手机上同一行 -->
      <div class="flex w-full items-center gap-2 sm:w-auto">
        <div class="relative min-w-0 flex-1 sm:w-72 sm:flex-none">
          <span class="pointer-events-none absolute top-1/2 left-3.5 -translate-y-1/2 text-mute"><Icon name="search" :size="17" /></span>
          <input v-model="keyword" type="search" class="field glass h-11 rounded-2xl pl-10 sm:h-11" placeholder="在收藏里搜索（含备注）" aria-label="在收藏里搜索" />
        </div>
        <div v-if="authState.user" class="relative shrink-0">
          <button class="btn-glass h-11 rounded-2xl px-3" :aria-expanded="exportOpen" title="导出收藏" @click="exportOpen = !exportOpen"><Icon name="download" :size="16" /><span class="max-sm:hidden">导出</span></button>
          <Transition name="drop">
            <div v-if="exportOpen" class="glass-strong absolute top-full right-0 z-30 mt-1.5 w-44 rounded-xl p-1.5 shadow-lg">
              <button class="menu-row" @click="exportFavs('md')"><Icon name="file-text" :size="14" />导出 Markdown</button>
              <button class="menu-row" @click="exportFavs('json')"><Icon name="code" :size="14" />导出 JSON</button>
            </div>
          </Transition>
        </div>
      </div>
    </section>

    <div v-if="authState.ready && !authState.user" class="panel mx-auto mt-6 flex max-w-md flex-col items-center gap-3 px-6 py-14 text-center">
      <span class="float-y grid h-14 w-14 place-items-center rounded-2xl bg-brand text-white"><Icon name="heart" :size="26" /></span>
      <p class="font-semibold">登录后查看你的收藏</p>
      <p class="text-sm text-ink-2">收藏和收藏分类是每个人自己的，换设备登录也在</p>
      <button class="btn-primary mt-1" @click="requireLogin()">登录 / 注册</button>
    </div>

    <div v-else-if="tree && !tree.total" class="panel mt-6 flex flex-col items-center gap-3 px-6 py-16 text-center">
      <span class="float-y grid h-14 w-14 place-items-center rounded-2xl bg-brand text-white"><Icon name="heart" :size="26" /></span>
      <p class="font-semibold">还没有收藏</p>
      <p class="text-sm text-ink-2">在主页或榜单里点卡片右上角的爱心，收藏后可以放进自己的分类</p>
      <RouterLink to="/" class="btn-primary mt-1">去逛逛</RouterLink>
    </div>

    <div v-else-if="tree" class="mt-5 lg:grid lg:grid-cols-[250px_minmax(0,1fr)] lg:gap-6">
      <!-- ============ 侧栏：维度与分类 ============ -->
      <aside class="lg:sticky lg:top-20 lg:self-start" aria-label="收藏分类">
        <!-- 维度切换 -->
        <div class="scrollbar-none -mx-4 flex gap-1.5 overflow-x-auto px-4 pb-1 lg:mx-0 lg:flex-wrap lg:px-0">
          <button
            v-for="d in [...dims, ...systemDims]"
            :key="d.system ? d.key : d.id"
            class="flex h-8 shrink-0 cursor-pointer items-center gap-1 rounded-full px-3 text-[13px] transition-all duration-300 ease-out-expo"
            :class="currentDim === d ? 'bg-ink font-medium text-white' : 'border border-edge bg-white/55 text-ink-2 hover:bg-white/90'"
            :aria-pressed="currentDim === d"
            @click="pickDim(d)"
          >
            <Icon v-if="d.system" name="layers" :size="13" />{{ d.name }}
          </button>
          <button class="flex h-8 shrink-0 cursor-pointer items-center gap-1 rounded-full px-2.5 text-[13px] text-brand hover:bg-brand-soft" title="新建维度" @click="addDimension">
            <Icon name="plus" :size="14" />维度
          </button>
        </div>

        <!-- 分类列表 -->
        <div v-if="currentDim" class="glass mt-3 rounded-2xl p-2">
          <div class="flex items-center gap-1 px-2 pt-1 pb-1.5 text-xs text-mute">
            <span class="min-w-0 flex-1 truncate">{{ currentDim.system ? '系统自动归组 · 只读' : currentDim.name }}</span>
            <template v-if="isCustom">
              <button class="cursor-pointer rounded-md p-1 hover:bg-white/80 hover:text-ink" title="重命名维度" aria-label="重命名维度" @click="renameDimension"><Icon name="pencil" :size="13" /></button>
              <button class="cursor-pointer rounded-md p-1 hover:bg-danger-soft hover:text-danger" title="删除维度" aria-label="删除维度" @click="deleteDimension"><Icon name="trash" :size="13" /></button>
            </template>
          </div>

          <ul class="scrollbar-none -mx-2 flex gap-1 overflow-x-auto px-2 lg:mx-0 lg:block lg:space-y-0.5 lg:overflow-visible lg:px-0">
            <li class="shrink-0">
              <button class="folder-row" :class="{ on: !folderKey }" @click="pickFolder('')">
                <Icon name="inbox" :size="15" class="text-mute" /><span class="flex-1 truncate text-left">全部收藏</span><em>{{ tree.total }}</em>
              </button>
            </li>
            <li v-if="isCustom" class="shrink-0">
              <button
                class="folder-row"
                :class="{ on: folderKey === 'none' }"
                @click="pickFolder('none')"
              >
                <Icon name="clock" :size="15" class="text-warn" /><span class="flex-1 truncate text-left">未整理</span>
                <em :class="currentDim.unsorted ? 'bg-warn-soft text-warn' : ''">{{ currentDim.unsorted }}</em>
              </button>
            </li>
            <li
              v-for="f in currentDim.folders"
              :key="f.id ?? f.key"
              class="group relative shrink-0"
              :draggable="isCustom && !editing"
              @dragstart="isCustom && (dragFolder = f)"
              @dragover.prevent="dropTarget = f"
              @dragleave="dropTarget === f && (dropTarget = null)"
              @drop.prevent="dragItem ? onFolderDrop(f.id ? f : null) : onFolderReorder(f)"
            >
              <form v-if="editing && editing.id === f.id" class="px-1 py-0.5" @submit.prevent="renameFolder">
                <input v-model="editing.name" class="field h-8 text-[13px] sm:h-8" maxlength="20" aria-label="分类名称" @blur="renameFolder" @keydown.esc="editing = null" />
              </form>
              <button
                v-else
                class="folder-row"
                :class="{ on: folderKey === String(f.id ?? f.key), drop: dropTarget === f && dragItem && f.id }"
                @click="pickFolder(String(f.id ?? f.key))"
              >
                <span class="w-[18px] text-center text-[15px] leading-none">{{ f.emoji || '📁' }}</span>
                <span class="flex-1 truncate text-left">{{ f.name }}</span>
                <em>{{ f.count }}</em>
              </button>
              <button
                v-if="isCustom && !editing"
                class="absolute top-1/2 right-9 hidden -translate-y-1/2 cursor-pointer rounded-md p-1 text-mute hover:bg-white hover:text-ink lg:group-hover:block"
                :aria-label="`管理分类 ${f.name}`"
                @click.stop="menuFor = menuFor === f.id ? null : f.id"
              ><Icon name="more" :size="15" /></button>
              <div v-if="menuFor === f.id" class="glass-strong absolute top-full right-2 z-30 mt-1 w-52 rounded-xl p-1.5 shadow-lg" @click.stop>
                <div class="grid grid-cols-6 gap-0.5 p-1">
                  <button v-for="e in EMOJIS" :key="e" class="cursor-pointer rounded-lg p-1 text-base hover:bg-brand-soft" :class="{ 'bg-brand-soft': f.emoji === e }" @click="setEmoji(f, e)">{{ e }}</button>
                </div>
                <button class="menu-row" @click="(editing = { id: f.id, name: f.name }), (menuFor = null)"><Icon name="pencil" :size="14" />重命名</button>
                <button class="menu-row" @click="shareFolder(f)"><Icon name="link" :size="14" />{{ f.share_token ? '复制分享链接' : '公开分享' }}</button>
                <button v-if="f.share_token" class="menu-row" @click="unshareFolder(f)"><Icon name="lock" :size="14" />停止分享</button>
                <button class="menu-row text-danger" @click="deleteFolder(f)"><Icon name="trash" :size="14" />删除分类</button>
              </div>
            </li>
          </ul>

          <form v-if="isCustom" class="mt-2 flex gap-1.5 px-1 pb-1" @submit.prevent="addFolder">
            <input v-model="newFolder" class="field h-9 min-w-0 flex-1 text-[13px] sm:h-9" maxlength="20" placeholder="新建分类" aria-label="新建分类" />
            <button class="btn-glass btn-sm shrink-0" :disabled="!newFolder.trim()" aria-label="新建分类"><Icon name="folder-plus" :size="15" /></button>
          </form>
          <p v-if="isCustom && currentDim.folders.length" class="hidden px-2 pt-1 pb-1 text-[11.5px] leading-relaxed text-mute lg:block">拖动卡片到分类即可归类；拖动分类可排序</p>
        </div>

        <button
          v-if="isCustom && currentDim.unsorted"
          class="mt-3 flex w-full cursor-pointer items-center gap-2 rounded-2xl border border-brand/20 bg-linear-135 from-brand/10 to-brand-2/10 px-3.5 py-3 text-left text-[13px] transition-all duration-300 hover:-translate-y-0.5 hover:shadow-md"
          :disabled="organizing"
          @click="organize"
        >
          <Icon name="wand" :size="17" class="text-brand" :class="{ 'animate-pulse': organizing }" />
          <span class="min-w-0 flex-1">
            <b class="block font-semibold">{{ organizing ? 'AI 正在看你的收藏…' : 'AI 帮我整理' }}</b>
            <span class="text-mute">按你的分类，给 {{ currentDim.unsorted }} 个未整理的收藏建议去处</span>
          </span>
        </button>
      </aside>

      <!-- ============ 列表 ============ -->
      <section class="mt-5 min-w-0 lg:mt-0">
        <div class="flex flex-wrap items-center gap-2">
          <h2 class="text-lg font-bold">{{ currentFolder?.emoji }} {{ title }}</h2>
          <span class="text-sm text-mute tabular-nums">{{ total }}</span>
          <template v-if="isCustom && currentFolder">
            <button class="cursor-pointer rounded-lg p-1.5 text-mute hover:bg-white/80 hover:text-ink lg:hidden" aria-label="重命名分类" @click="renameCurrent"><Icon name="pencil" :size="14" /></button>
            <button class="cursor-pointer rounded-lg p-1.5 text-mute hover:bg-danger-soft hover:text-danger lg:hidden" aria-label="删除分类" @click="deleteFolder(currentFolder)"><Icon name="trash" :size="14" /></button>
          </template>
          <div class="ml-auto flex items-center gap-1.5">
            <AppSelect
              :model-value="sort"
              :options="SORTS"
              label="排序"
              size="sm"
              align="right"
              class="w-32"
              @update:model-value="(v) => go({ sort: v })"
            />
            <CompareModeToggle v-if="items.length && !selecting" class="h-9" />
            <button v-if="items.length" class="btn-glass btn-sm" :class="{ 'text-brand': selecting }" @click="selecting ? exitSelect() : (selecting = true)">
              <Icon :name="selecting ? 'x' : 'check'" :size="15" />{{ selecting ? '完成' : '多选' }}
            </button>
          </div>
        </div>

        <div v-if="loading && !items.length" class="mt-3 grid grid-cols-2 gap-2.5 sm:grid-cols-2 sm:gap-3.5 xl:grid-cols-3">
          <div v-for="n in 6" :key="n" class="skeleton-bar h-56 rounded-[12px] max-sm:h-36 max-sm:rounded-xl" />
        </div>
        <div v-else-if="!items.length" class="panel mt-3 flex flex-col items-center gap-2 px-6 py-12 text-center text-sm text-ink-2">
          <Icon name="inbox" :size="34" class="text-mute" />
          <p v-if="route.query.q">没有符合「{{ route.query.q }}」的收藏</p>
          <p v-else-if="folderKey === 'none'">都整理好了 🎉</p>
          <p v-else-if="isCustom && folderKey">这个分类还是空的。{{ selecting ? '' : '在「全部收藏」里多选或拖动卡片到这里' }}</p>
          <p v-else>没有收藏</p>
        </div>

        <div v-else class="mt-3 grid grid-cols-2 gap-2.5 sm:grid-cols-2 sm:gap-3.5 xl:grid-cols-3">
          <div
            v-for="(it, i) in items"
            :key="it.id"
            class="relative rounded-[12px] transition-transform duration-300 max-sm:rounded-xl"
            :class="{ 'scale-[0.98] ring-2 ring-brand ring-offset-2 ring-offset-transparent': selecting && selected.has(it.id) }"
            draggable="true"
            @dragstart="onCardDragStart($event, it)"
            @dragend="dragItem = null"
            @pointerdown="pressStart($event, it)"
            @pointerup="pressEnd"
            @pointerleave="pressEnd"
            @pointercancel="pressEnd"
            @contextmenu="selecting && $event.preventDefault()"
            @click.capture="onCardClick($event, it)"
          >
            <ItemCard :item="it" :index="i" :base="base" dense :no-compare="selecting" />
            <span
              v-if="selecting"
              class="pointer-events-none absolute top-2.5 left-2.5 z-20 grid h-7 w-7 max-sm:top-1 max-sm:left-1 max-sm:h-6 max-sm:w-6 place-items-center rounded-full border-2 transition-all duration-200"
              :class="selected.has(it.id) ? 'border-brand bg-brand text-white' : 'border-white bg-white/70'"
            ><Icon v-if="selected.has(it.id)" name="check" :size="15" /></span>
          </div>
        </div>

        <div class="mt-6 flex justify-center">
          <button v-if="items.length < total" class="btn-glass w-full sm:w-auto" :disabled="loading" @click="more">{{ loading ? '加载中…' : '加载更多' }}</button>
        </div>
      </section>
    </div>

    <!-- 多选操作栏 -->
    <Transition name="toast">
      <div v-if="selecting" class="fixed inset-x-0 bottom-[calc(76px+env(safe-area-inset-bottom))] z-40 flex justify-center px-3 sm:bottom-6">
        <div class="glass-strong relative flex w-full max-w-xl flex-wrap items-center gap-2 rounded-2xl p-2.5 pl-4 shadow-[0_16px_36px_-14px_rgb(11_47_122/0.55)]">
          <span class="text-[13px] text-ink-2">已选 <b class="text-ink tabular-nums">{{ selected.size }}</b></span>
          <button class="cursor-pointer text-[13px] text-brand hover:underline" @click="selectAll">{{ selected.size === items.length ? '全不选' : '全选' }}</button>
          <div class="ml-auto flex flex-wrap gap-1.5">
            <button class="btn-primary btn-sm" :disabled="!selected.size || !dims.length" @click="moveMenu = !moveMenu"><Icon name="folder" :size="15" />放进分类</button>
            <button v-if="isCustom && currentFolder" class="btn-glass btn-sm" :disabled="!selected.size" @click="moveTo([], [currentFolder.id])">移出此分类</button>
            <button class="btn-glass btn-sm text-danger" :disabled="!selected.size" @click="unfavSelected"><Icon name="heart" :size="15" />取消收藏</button>
          </div>
          <div v-if="moveMenu" class="glass-strong absolute right-2 bottom-full mb-2 max-h-72 w-64 overflow-y-auto rounded-2xl p-2 shadow-lg">
            <template v-for="d in dims" :key="d.id">
              <p class="px-2 pt-1.5 pb-1 text-[11.5px] font-semibold text-mute">{{ d.name }}</p>
              <button v-for="f in d.folders" :key="f.id" class="menu-row" @click="moveTo([f.id])">{{ f.emoji || '📁' }} {{ f.name }}</button>
              <p v-if="!d.folders.length" class="px-2 pb-1 text-xs text-mute">还没有分类</p>
            </template>
          </div>
        </div>
      </div>
    </Transition>

    <!-- 撤销条 -->
    <Transition name="toast">
      <div v-if="undo && !selecting" class="fixed inset-x-0 bottom-[calc(80px+env(safe-area-inset-bottom))] z-40 flex justify-center px-4 sm:bottom-8">
        <div class="flex items-center gap-3 rounded-2xl bg-ink px-4 py-2.5 text-sm text-white shadow-lg">
          <span>{{ undo.message }}</span>
          <button class="flex cursor-pointer items-center gap-1 font-semibold text-blue-200 hover:text-white" @click="runUndo"><Icon name="undo" :size="15" />撤销</button>
        </div>
      </div>
    </Transition>

    <!-- AI 整理建议 -->
    <Teleport to="body">
      <Transition name="toast">
        <div v-if="suggestions && suggestions.length" class="fixed inset-0 z-[60] grid place-items-center bg-ink/25 p-4 backdrop-blur-[3px]" role="dialog" aria-modal="true" aria-label="AI 整理建议" @click.self="suggestions = null">
          <div class="glass-strong flex max-h-[80vh] w-full max-w-lg flex-col rounded-[12px] shadow-2xl">
            <div class="flex items-center gap-2 border-b border-line px-5 py-4">
              <Icon name="wand" :size="18" class="text-brand" />
              <h2 class="font-bold">AI 整理建议</h2>
              <AiTag />
              <button class="ml-auto cursor-pointer rounded-xl p-1.5 text-mute hover:bg-white" aria-label="关闭" @click="suggestions = null"><Icon name="x" :size="18" /></button>
            </div>
            <ul class="flex-1 divide-y divide-line overflow-y-auto px-2">
              <li v-for="s in suggestions" :key="s.item_id">
                <div class="flex cursor-pointer items-start gap-3 rounded-xl px-3 py-2.5 hover:bg-white/60" @click="s.on = !s.on">
                  <CheckBox :checked="s.on" class="mt-1" :label="s.item_name" @toggle="s.on = !s.on" />
                  <span class="min-w-0 flex-1">
                    <b class="block truncate text-[14px] font-semibold">{{ s.item_name }}</b>
                    <span class="mt-1 flex flex-wrap gap-1">
                      <span v-for="fid in s.folder_ids" :key="fid" class="tag border border-edge bg-white/80 text-ink-2">→ {{ folderName(fid) }}</span>
                      <span v-if="s.new_folder" class="tag bg-brand-soft text-brand">→ 新建「{{ s.new_folder }}」</span>
                    </span>
                  </span>
                </div>
              </li>
            </ul>
            <div class="flex items-center gap-2 border-t border-line px-5 py-3.5">
              <span class="text-[13px] text-mute">只是建议，确认后才会移动</span>
              <button class="btn-primary btn-sm ml-auto" @click="applySuggestions">应用 {{ suggestions.filter((s) => s.on).length }} 条</button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- 详情抽屉 -->
    <RouterView v-if="!embedded" v-slot="{ Component }">
      <Transition name="sheet">
        <component :is="Component" v-if="Component" />
      </Transition>
    </RouterView>
  </div>
</template>

<style scoped>
.folder-row {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  height: 38px;
  padding: 0 10px;
  border-radius: 12px;
  font-size: 13.5px;
  color: var(--color-ink-2);
  cursor: pointer;
  white-space: nowrap;
  transition: background-color 0.2s, color 0.2s, box-shadow 0.2s;
}
.folder-row:hover {
  background: rgb(255 255 255 / 0.7);
}
.folder-row.on {
  background: #fff;
  color: var(--color-ink);
  font-weight: 600;
  box-shadow: 0 2px 10px -4px rgb(11 47 122 / 0.3);
}
.folder-row.drop {
  background: var(--color-brand-soft);
  box-shadow: inset 0 0 0 2px var(--color-brand);
}
.folder-row em {
  min-width: 22px;
  padding: 0 6px;
  border-radius: 999px;
  font-style: normal;
  font-size: 11.5px;
  text-align: center;
  color: var(--color-mute);
  font-variant-numeric: tabular-nums;
}
.menu-row {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 8px 10px;
  border-radius: 10px;
  font-size: 13px;
  text-align: left;
  cursor: pointer;
}
.menu-row:hover {
  background: var(--color-brand-soft);
}
@media (max-width: 1023px) {
  .folder-row {
    width: auto;
    border: 1px solid var(--color-edge);
    background: rgb(255 255 255 / 0.5);
  }
}
</style>
