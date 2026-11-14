<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api, isCancelled } from '../../api'
import Icon from '../../components/Icon.vue'

// 全局搜索：邮箱 / 昵称 / 条目名 / 编号，直达详情。快捷键 Ctrl+K 或 /（不在输入框里时）。
//   接口 GET /api/admin/search?q=&limit=5 → { users: [], items: [], feedback: [] }
const router = useRouter()
const open = ref(false)
const q = ref('')
const input = ref(null)
const data = ref(null)
const loading = ref(false)
const active = ref(0)
let timer
let seq = 0

const GROUPS = [
  { key: 'users', title: '用户', icon: 'user', label: (r) => r.label, sub: (r) => [r.sub, r.status_label].filter(Boolean).join(' · '), to: (r) => ({ path: '/users', query: { id: r.id } }) },
  { key: 'items', title: '条目', icon: 'package', label: (r) => r.label, sub: (r) => [r.sub, r.status_label].filter(Boolean).join(' · '), to: (r) => ({ path: '/content', query: { id: r.id } }) },
  { key: 'feedback', title: '用户反馈', icon: 'message', label: (r) => r.label, sub: (r) => [r.sub, r.status_label].filter(Boolean).join(' · '), to: (r) => ({ path: '/feedback', query: { id: r.id } }) },
]
// 键盘上下选择用的扁平列表
const flat = computed(() => GROUPS.flatMap((g) => (data.value?.[g.key] || []).map((r) => ({ g, r }))))
const empty = computed(() => data.value && !flat.value.length)

const searchable = (s) => /^\d+$/.test(s.trim()) || s.trim().length >= 2
async function run() {
  const mine = ++seq
  const s = q.value.trim()
  if (!searchable(s)) {
    data.value = null
    loading.value = false
    return
  }
  loading.value = true
  try {
    const d = await api(`/api/admin/search?${new URLSearchParams({ q: s, limit: 5 })}`)
    if (mine === seq) {
      data.value = d
      active.value = 0
    }
  } catch (e) {
    if (mine === seq && !isCancelled(e)) data.value = { users: [], items: [], feedback: [] }
  } finally {
    if (mine === seq) loading.value = false
  }
}
watch(q, () => {
  clearTimeout(timer)
  timer = setTimeout(run, 200)
})

function show() {
  open.value = true
  q.value = ''
  data.value = null
  nextTick(() => input.value?.focus())
}
function hide() {
  open.value = false
}
function go(item) {
  hide()
  router.push(item.g.to(item.r))
}
function onInputKey(e) {
  if (e.key === 'ArrowDown') active.value = Math.min(flat.value.length - 1, active.value + 1)
  else if (e.key === 'ArrowUp') active.value = Math.max(0, active.value - 1)
  else if (e.key === 'Enter' && flat.value[active.value]) go(flat.value[active.value])
  else return
  e.preventDefault()
  nextTick(() => document.querySelector('[data-search-active]')?.scrollIntoView({ block: 'nearest' }))
}

function onKey(e) {
  if (open.value) {
    if (e.key === 'Escape') hide()
    return
  }
  const typing = ['INPUT', 'TEXTAREA'].includes(document.activeElement?.tagName) || document.activeElement?.isContentEditable
  if ((e.key === 'k' && (e.ctrlKey || e.metaKey)) || (e.key === '/' && !typing && !e.ctrlKey && !e.metaKey)) {
    e.preventDefault()
    show()
  }
}
onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKey)
  clearTimeout(timer)
})
</script>

<template>
  <button type="button" class="btn h-9 gap-2 px-2.5 text-mute sm:w-56 sm:justify-start" aria-label="搜索" @click="show">
    <Icon name="search" :size="15" /><span class="hidden sm:inline">搜索用户、条目、编号</span><kbd class="ml-auto hidden rounded border border-line px-1.5 font-mono text-[11px] sm:inline">Ctrl K</kbd>
  </button>
  <Teleport to="body">
    <Transition name="fade">
      <div v-if="open" class="fixed inset-0 z-50 bg-ink/35 sm:px-4 sm:pt-[12vh]" @click.self="hide">
        <div class="card mx-auto flex h-full w-full flex-col overflow-hidden rounded-none shadow-[0_20px_50px_-20px_rgba(15,29,51,.35)] sm:h-auto sm:max-h-[70vh] sm:max-w-[560px] sm:rounded-lg" role="dialog" aria-modal="true" aria-label="全局搜索">
          <div class="flex items-center gap-2.5 border-b border-line px-4">
            <Icon name="search" :size="16" class="shrink-0 text-mute" />
            <input ref="input" v-model="q" class="h-12 min-w-0 flex-1 border-0 bg-transparent text-[15px] outline-none placeholder:text-mute" placeholder="邮箱、昵称、条目名、编号" aria-label="搜索" autocomplete="off" @keydown="onInputKey" />
            <button class="btn h-9 shrink-0 px-2.5 text-mute" @click="hide">关闭</button>
          </div>
          <div class="min-h-0 flex-1 overflow-y-auto p-2">
            <p v-if="loading && !data" class="px-3 py-6 text-center text-[13px] text-mute">搜索中…</p>
            <p v-else-if="empty" class="px-3 py-6 text-center text-[13px] text-mute">没有找到「{{ q.trim() }}」</p>
            <template v-else-if="data">
              <section v-for="g in GROUPS.filter((x) => data[x.key]?.length)" :key="g.key" class="mb-1">
                <p class="cap px-2.5 pt-2 pb-1">{{ g.title }}</p>
                <button
                  v-for="r in data[g.key]"
                  :key="r.id"
                  type="button"
                  class="flex min-h-10 w-full items-center gap-2.5 rounded-md px-2.5 py-1.5 text-left text-[13.5px]"
                  :class="flat[active]?.r === r ? 'bg-primary-soft' : 'hover:bg-subtle'"
                  :data-search-active="flat[active]?.r === r || undefined"
                  @mouseenter="active = flat.findIndex((x) => x.r === r)"
                  @click="go({ g, r })"
                >
                  <Icon :name="g.icon" :size="15" class="shrink-0 text-mute" />
                  <span class="min-w-0 flex-1 truncate">{{ g.label(r) }}</span>
                  <span class="shrink-0 text-xs text-mute">{{ g.sub(r) }}</span>
                </button>
              </section>
            </template>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>
