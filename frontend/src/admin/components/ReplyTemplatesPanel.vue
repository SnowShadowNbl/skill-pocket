<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, isCancelled } from '../../api'
import Icon from '../../components/Icon.vue'
import { authState } from '../../composables/auth'
import { confirmDialog, promptDialog } from '../../composables/dialog'
import { toast } from '../../composables/toast'

// 回复模板（反馈回复、站内消息）：标题 + 正文，正文里可以用 {nickname}（用户昵称）、{id}（反馈编号）。所有管理员能看，只有超级管理员能改
const route = useRoute()
const router = useRouter()
const isSuper = computed(() => authState.user?.role === 'admin')
const data = ref(null)
const scope = computed(() => (data.value && route.query.rscope in data.value.scopes ? route.query.rscope : 'feedback_reply'))
const setScope = (k) => router.replace({ query: { ...route.query, rscope: k === 'feedback_reply' ? undefined : k } })
const busy = ref(false)

async function load() {
  try {
    data.value = await api(`/api/admin/reply-templates?scope=${route.query.rscope || 'feedback_reply'}`)
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  }
}
watch(() => route.query.rscope, load, { immediate: true })
const scopes = computed(() => Object.entries(data.value?.scopes || { feedback_reply: '反馈回复' }))
const items = computed(() => (data.value?.items || []).filter((t) => t.scope === scope.value).sort((a, b) => a.position - b.position || a.id - b.id))
const vars = computed(() => Object.entries(data.value?.variables || {}).map(([k, v]) => `${k} ${v}`).join('，'))

async function guard(fn) {
  busy.value = true
  try {
    await fn()
    await load()
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  } finally {
    busy.value = false
  }
}
async function ask(t) {
  const title = await promptDialog({ title: t ? '修改标题' : '新增模板：标题', value: t?.title || '', placeholder: '例如：已修复', maxlength: 40, required: true, okText: '下一步' })
  if (!title) return null
  const text = await promptDialog({ title: '正文', message: vars.value, value: t?.text || '', placeholder: '{nickname}你好，…', maxlength: 500, required: true, okText: t ? '保存' : '添加' })
  return text ? { title, text } : null
}
async function add() {
  const v = await ask()
  if (v) await guard(() => api('/api/admin/reply-templates', { method: 'POST', body: { scope: scope.value, ...v } }))
}
async function edit(t) {
  const v = await ask(t)
  if (v) await guard(() => api(`/api/admin/reply-templates/${t.id}`, { method: 'PUT', body: v }))
}
async function remove(t) {
  if (!(await confirmDialog({ title: `删除模板「${t.title}」？`, okText: '删除', danger: true }))) return
  await guard(() => api(`/api/admin/reply-templates/${t.id}`, { method: 'DELETE' }))
}
async function move(t, dir) {
  const list = items.value
  const o = list[list.findIndex((x) => x.id === t.id) + dir]
  if (!o) return
  await guard(async () => {
    const [pa, pb] = [t.position, o.position]
    await api(`/api/admin/reply-templates/${t.id}`, { method: 'PUT', body: { position: pb } })
    await api(`/api/admin/reply-templates/${o.id}`, { method: 'PUT', body: { position: pa } })
  })
}
</script>

<template>
  <section class="card mt-5">
    <div class="flex flex-wrap items-center gap-2 border-b border-line px-3.5 py-3">
      <div class="seg"><button v-for="[k, name] in scopes" :key="k" :class="{ on: scope === k }" @click="setScope(k)">{{ name }}</button></div>
      <button v-if="isSuper" class="btn btn-primary ml-auto" :disabled="busy" @click="add"><Icon name="plus" :size="14" />新增模板</button>
      <span v-else class="ml-auto text-xs text-mute">只有超级管理员能修改</span>
    </div>
    <div v-if="!data" class="p-3.5"><div class="skeleton h-40" /></div>
    <p v-else-if="!items.length" class="empty">这个场景还没有模板</p>
    <ul v-else class="m-0 list-none p-0">
      <li v-for="(t, i) in items" :key="t.id" class="flex items-start gap-2 border-b border-line px-4 py-3 last:border-0">
        <span class="min-w-0 flex-1"><b class="block text-[13.5px] font-medium">{{ t.title }}</b><span class="mt-0.5 block text-[13px] break-words whitespace-pre-wrap text-ink-2">{{ t.text }}</span></span>
        <template v-if="isSuper">
          <button class="grid h-10 w-9 place-items-center text-mute hover:text-primary disabled:opacity-30" aria-label="上移" :disabled="busy || i === 0" @click="move(t, -1)"><Icon name="chevron-up" :size="15" /></button>
          <button class="grid h-10 w-9 place-items-center text-mute hover:text-primary disabled:opacity-30" aria-label="下移" :disabled="busy || i === items.length - 1" @click="move(t, 1)"><Icon name="chevron-down" :size="15" /></button>
          <button class="grid h-10 w-9 place-items-center text-mute hover:text-primary" aria-label="修改" :disabled="busy" @click="edit(t)"><Icon name="pencil" :size="14" /></button>
          <button class="grid h-10 w-9 place-items-center text-mute hover:text-bad" aria-label="删除" :disabled="busy" @click="remove(t)"><Icon name="trash" :size="14" /></button>
        </template>
      </li>
    </ul>
  </section>
</template>
