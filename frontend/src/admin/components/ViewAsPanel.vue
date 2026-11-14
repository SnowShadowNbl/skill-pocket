<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { api, formatTime, isCancelled } from '../../api'
import Icon from '../../components/Icon.vue'
import { toast } from '../../composables/toast'

// 以用户视角只读查看：全屏只读面板，限时 15 分钟，读取都会留日志。
//   <ViewAsPanel :open :user-id :name :session="{ session_id, expires_at, sections }" @close />
const props = defineProps({ open: Boolean, userId: { type: Number, default: 0 }, name: { type: String, default: '' }, session: { type: Object, default: null } })
const emit = defineEmits(['close'])
const section = ref('pocket')
const data = ref(null)
const busy = ref(false)
const now = ref(Date.now())
let timer

const sections = computed(() => Object.entries(props.session?.sections || {}))
const left = computed(() => (props.session ? Math.max(0, Math.round((new Date(props.session.expires_at) - now.value) / 1000)) : 0))
const clock = computed(() => `${Math.floor(left.value / 60)}:${String(left.value % 60).padStart(2, '0')}`)

async function load(more = false) {
  if (!props.session) return
  const page = more ? data.value.page + 1 : 1
  busy.value = true
  try {
    const d = await api(`/api/admin/users/${props.userId}/view/${section.value}?session_id=${encodeURIComponent(props.session.session_id)}&page=${page}`)
    data.value = more ? { ...d, items: [...data.value.items, ...d.items] } : d
  } catch (e) {
    if (e.code === 'view_expired') {
      toast('查看已过期，请重新开启', 'info')
      emit('close')
    } else if (!isCancelled(e)) toast(e.message, 'error')
  } finally {
    busy.value = false
  }
}
watch(() => [props.open, props.session?.session_id], ([o]) => {
  clearInterval(timer)
  data.value = null
  if (!o || !props.session) return
  section.value = 'pocket'
  now.value = Date.now()
  timer = setInterval(() => {
    now.value = Date.now()
    if (left.value <= 0) {
      clearInterval(timer)
      toast('查看已过期', 'info')
      emit('close')
    }
  }, 1000)
  load()
})
watch(section, () => {
  data.value = null
  load()
})
onBeforeUnmount(() => clearInterval(timer))

const folderName = computed(() => {
  const m = {}
  for (const d of data.value?.dimensions || []) for (const f of d.folders) m[f.id] = `${f.emoji || ''}${f.name}`
  return m
})
const hasMore = computed(() => data.value && data.value.items && data.value.items.length < data.value.total)
</script>

<template>
  <Transition name="fade">
    <div v-if="open && session" class="fixed inset-0 z-[45] flex flex-col bg-canvas">
      <header class="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-warn/40 bg-warn-soft px-4 py-2.5 text-[13px] text-warn">
        <Icon name="eye" :size="16" />
        <b class="font-semibold">只读视图</b><span>正在以「{{ name }}」的视角查看</span>
        <span class="tabular-nums">剩余 {{ clock }}</span>
        <button class="btn ml-auto h-9 !border-warn/40 !text-warn" @click="emit('close')">结束查看</button>
      </header>
      <nav class="flex gap-1 overflow-x-auto border-b border-line bg-white px-4">
        <button v-for="[k, label] in sections" :key="k" class="-mb-px h-11 shrink-0 border-b-2 px-3 text-[13.5px]" :class="section === k ? 'border-primary font-semibold text-primary' : 'border-transparent text-ink-2 hover:text-ink'" @click="section = k">{{ label }}</button>
      </nav>
      <div class="min-h-0 flex-1 overflow-y-auto px-4 py-4">
        <div class="mx-auto max-w-[760px]">
          <div v-if="!data" class="skeleton h-60" />
          <template v-else>
            <!-- 口袋 -->
            <template v-if="section === 'pocket'">
              <p v-for="d in data.dimensions" :key="d.id" class="m-0 mb-2 flex flex-wrap items-center gap-1.5 text-[13px]"><b class="font-medium">{{ d.name }}</b><span v-for="f in d.folders" :key="f.id" class="tag" :class="f.shared ? 'tag-blue' : 'tag-gray'">{{ f.emoji }}{{ f.name }}<template v-if="f.shared"> · 分享中</template></span></p>
              <h3 class="mt-3 mb-2 text-[13px] font-semibold">收藏的条目<span class="ml-1.5 font-normal text-mute tabular-nums">{{ data.total }}</span></h3>
              <p v-if="!data.items.length" class="empty">口袋是空的</p>
              <ul class="m-0 list-none p-0">
                <li v-for="x in data.items" :key="x.item.id" class="card mb-2 flex gap-3 p-3">
                  <span class="h-12 w-16 shrink-0 overflow-hidden rounded-md border border-line bg-subtle"><img v-if="x.item.cover_url" :src="x.item.cover_url" alt="" class="h-full w-full object-cover" loading="lazy" /></span>
                  <span class="min-w-0 flex-1 text-[13px]">
                    <b class="block truncate font-semibold">{{ x.item.name }}</b>
                    <span class="block truncate text-xs text-mute">{{ x.item.repo || x.item.summary }}</span>
                    <span v-if="x.folder_ids?.length" class="mt-1 flex flex-wrap gap-1"><span v-for="id in x.folder_ids" :key="id" class="tag tag-gray !h-[18px] !px-1.5 !text-[11px]">{{ folderName[id] || id }}</span></span>
                    <span v-if="x.note" class="mt-1 block text-xs text-ink-2">备注：{{ x.note }}</span>
                  </span>
                  <time class="shrink-0 text-xs text-mute">{{ formatTime(x.at, false) }}</time>
                </li>
              </ul>
            </template>
            <!-- 订阅 -->
            <template v-else-if="section === 'subscriptions'">
              <p v-if="!data.items.length" class="empty">没有订阅</p>
              <ul class="m-0 list-none p-0"><li v-for="(x, i) in data.items" :key="i" class="card mb-2 flex items-center gap-2 px-3 py-2.5 text-[13px]"><b class="font-medium">{{ x.name }}</b><span v-if="x.is_parent" class="tag tag-gray">大类</span><span class="ml-auto text-xs text-mute">订阅于 {{ formatTime(x.since, false) }}<template v-if="x.last_notified_at"> · 最近推送 {{ formatTime(x.last_notified_at, false) }}</template></span></li></ul>
            </template>
            <!-- 通知 -->
            <template v-else-if="section === 'notifications'">
              <p class="m-0 mb-2 text-[13px] text-mute">共 {{ data.total }} 条，未读 <b class="text-ink tabular-nums">{{ data.unread }}</b></p>
              <p v-if="!data.items.length" class="empty">没有通知</p>
              <ul class="m-0 list-none p-0">
                <li v-for="x in data.items" :key="x.id" class="card mb-2 px-3 py-2.5 text-[13px]">
                  <span class="flex items-center gap-2"><span class="tag tag-gray">{{ x.kind_label }}</span><b class="min-w-0 flex-1 truncate font-medium">{{ x.title }}</b><span class="tag" :class="x.read_at ? 'tag-gray' : 'tag-warn'">{{ x.read_at ? '已读' : '未读' }}</span></span>
                  <span v-if="x.text" class="mt-1 block text-xs break-words text-ink-2">{{ x.text }}</span>
                  <time class="mt-1 block text-xs text-mute">{{ formatTime(x.at) }}</time>
                </li>
              </ul>
            </template>
            <!-- 评论 -->
            <template v-else-if="section === 'comments'">
              <p v-if="!data.items.length" class="empty">没有评论</p>
              <ul class="m-0 list-none p-0"><li v-for="x in data.items" :key="x.id" class="card mb-2 px-3 py-2.5 text-[13px]"><span class="flex flex-wrap items-center gap-1.5"><b class="font-medium">{{ x.item.name }}</b><b v-if="x.rating != null" class="text-warn">★{{ x.rating }}</b><span class="tag tag-gray">{{ x.status }}</span><time class="ml-auto text-xs text-mute">{{ formatTime(x.at, false) }}</time></span><span v-if="x.content" class="mt-1 block break-words text-ink-2">{{ x.content }}</span></li></ul>
            </template>
            <!-- AI 对比 -->
            <template v-else>
              <p v-if="!data.items.length" class="empty">没有对比记录</p>
              <ul class="m-0 list-none p-0"><li v-for="x in data.items" :key="x.id" class="card mb-2 flex items-center gap-2 px-3 py-2.5 text-[13px]"><span class="min-w-0 flex-1 truncate">{{ (x.names || []).join(' · ') }}</span><span class="tag tag-gray">{{ x.status }}</span><time class="text-xs text-mute">{{ formatTime(x.at) }}</time></li></ul>
            </template>
            <button v-if="hasMore" class="btn btn-sm mt-1" :disabled="busy" @click="load(true)">加载更多</button>
          </template>
        </div>
      </div>
    </div>
  </Transition>
</template>
