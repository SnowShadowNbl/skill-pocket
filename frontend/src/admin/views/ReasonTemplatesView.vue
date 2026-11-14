<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, isCancelled } from '../../api'
import Icon from '../../components/Icon.vue'
import { authState } from '../../composables/auth'
import { confirmDialog, promptDialog } from '../../composables/dialog'
import { toast } from '../../composables/toast'
import ReplyTemplatesPanel from '../components/ReplyTemplatesPanel.vue'
import { resetReasonTemplates } from '../composables/useReasonTemplates'

// 驳回 / 处置原因模板：条目驳回、条目下架、评论驳回、评论删除、关闭分享。所有管理员能看，只有超级管理员能改
const route = useRoute()
const router = useRouter()
const mode = computed(() => (route.query.mode === 'reply' ? 'reply' : 'reason'))
const setMode = (m) => router.replace({ query: { mode: m === 'reply' ? 'reply' : undefined } })
const isSuper = computed(() => authState.user?.role === 'admin')
const data = ref(null)
const scope = computed(() => (data.value && route.query.scope in data.value.scopes ? route.query.scope : 'item_reject'))
const setScope = (k) => router.replace({ query: { scope: k === 'item_reject' ? undefined : k } })
const busy = ref(false)

async function load() {
  try {
    data.value = await api(`/api/admin/reason-templates?scope=${scope.value}`)
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  }
}
watch(() => route.query.scope, () => mode.value === 'reason' && load(), { immediate: true })
const scopes = computed(() => Object.entries(data.value?.scopes || { item_reject: '驳回条目' }))
const items = computed(() => (data.value?.items || []).filter((t) => t.scope === scope.value).sort((a, b) => a.position - b.position || a.id - b.id))

async function guard(fn) {
  busy.value = true
  try {
    await fn()
    resetReasonTemplates(scope.value)
    await load()
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  } finally {
    busy.value = false
  }
}
async function add() {
  const text = await promptDialog({ title: '新增模板', placeholder: '例如：与已有条目重复', maxlength: 60, required: true, okText: '添加' })
  if (!text) return
  await guard(() => api('/api/admin/reason-templates', { method: 'POST', body: { scope: scope.value, text } }))
}
async function edit(t) {
  const text = await promptDialog({ title: '修改模板', value: t.text, maxlength: 60, required: true, okText: '保存' })
  if (!text || text === t.text) return
  await guard(() => api(`/api/admin/reason-templates/${t.id}`, { method: 'PUT', body: { text } }))
}
async function remove(t) {
  if (!(await confirmDialog({ title: '删除这条模板？', message: t.text, okText: '删除', danger: true }))) return
  await guard(() => api(`/api/admin/reason-templates/${t.id}`, { method: 'DELETE' }))
}
// 上下移动：和相邻一条交换位置
async function move(t, dir) {
  const list = items.value
  const i = list.findIndex((x) => x.id === t.id)
  const o = list[i + dir]
  if (!o) return
  await guard(async () => {
    const [pa, pb] = [t.position, o.position]
    await api(`/api/admin/reason-templates/${t.id}`, { method: 'PUT', body: { position: pb } })
    await api(`/api/admin/reason-templates/${o.id}`, { method: 'PUT', body: { position: pa } })
  })
}
</script>

<template>
  <div>
    <div class="flex flex-wrap items-center gap-3">
      <h1 class="m-0 text-xl font-semibold">话术模板</h1>
      <div class="seg"><button :class="{ on: mode === 'reason' }" @click="setMode('reason')">处置原因</button><button :class="{ on: mode === 'reply' }" @click="setMode('reply')">回复模板</button></div>
      <button v-if="isSuper && mode === 'reason'" class="btn btn-primary ml-auto" :disabled="busy" @click="add"><Icon name="plus" :size="14" />新增模板</button>
    </div>

    <ReplyTemplatesPanel v-if="mode === 'reply'" />
    <section v-else class="card mt-5">
      <div class="flex flex-wrap items-center gap-2 border-b border-line px-3.5 py-3">
        <div class="seg flex-wrap">
          <button v-for="[k, name] in scopes" :key="k" :class="{ on: scope === k }" @click="setScope(k)">{{ name }}</button>
        </div>
        <span v-if="!isSuper" class="ml-auto text-xs text-mute">只有超级管理员能修改</span>
      </div>
      <div v-if="!data" class="p-3.5"><div class="skeleton h-40" /></div>
      <p v-else-if="!items.length" class="empty">这个场景还没有模板</p>
      <ul v-else class="m-0 list-none p-0">
        <li v-for="(t, i) in items" :key="t.id" class="flex items-center gap-2 border-b border-line px-4 py-2.5 last:border-0">
          <span class="min-w-0 flex-1 break-words text-[13.5px]">{{ t.text }}</span>
          <template v-if="isSuper">
            <button class="grid h-10 w-9 place-items-center text-mute hover:text-primary disabled:opacity-30" aria-label="上移" :disabled="busy || i === 0" @click="move(t, -1)"><Icon name="chevron-up" :size="15" /></button>
            <button class="grid h-10 w-9 place-items-center text-mute hover:text-primary disabled:opacity-30" aria-label="下移" :disabled="busy || i === items.length - 1" @click="move(t, 1)"><Icon name="chevron-down" :size="15" /></button>
            <button class="grid h-10 w-9 place-items-center text-mute hover:text-primary" aria-label="修改" :disabled="busy" @click="edit(t)"><Icon name="pencil" :size="14" /></button>
            <button class="grid h-10 w-9 place-items-center text-mute hover:text-bad" aria-label="删除" :disabled="busy" @click="remove(t)"><Icon name="trash" :size="14" /></button>
          </template>
        </li>
      </ul>
    </section>
  </div>
</template>
