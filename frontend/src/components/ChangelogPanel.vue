<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api, formatTime } from '../api'
import Icon from './Icon.vue'
import { openFeedback } from '../composables/feedback'

const open = ref(false)
const data = ref(null)
const filter = ref('')
const seen = ref(readSeen())

const CAT_STYLE = {
  feature: ['新增功能', 'bg-ok-soft text-ok', 'plus'],
  change: ['修改功能', 'bg-brand-soft text-brand', 'pencil'],
  fix: ['修复 Bug', 'bg-warn-soft text-warn', 'wrench'],
}
const FILTERS = [['', '全部'], ['feature', '新增功能'], ['change', '修改功能'], ['fix', '修复 Bug']]

const hasNew = computed(() => data.value?.latest && data.value.latest !== seen.value)
const releases = computed(() =>
  (data.value?.releases || [])
    .map((r) => ({ ...r, entries: r.entries.filter((e) => !filter.value || e.category === filter.value) }))
    .filter((r) => r.entries.length),
)
const counts = computed(() => {
  const c = { '': 0, feature: 0, change: 0, fix: 0 }
  for (const r of data.value?.releases || []) for (const e of r.entries) {
    c[''] += 1
    c[e.category] += 1
  }
  return c
})

function readSeen() {
  try {
    return localStorage.getItem('skillbase.changelogSeen') || ''
  } catch {
    return ''
  }
}

async function load() {
  try {
    data.value = await api('/api/changelog')
  } catch {}
}

function show() {
  open.value = true
  document.body.style.overflow = 'hidden'
  if (data.value?.latest) {
    seen.value = data.value.latest
    try {
      localStorage.setItem('skillbase.changelogSeen', data.value.latest)
    } catch {}
  }
}
// 先关掉更新日志，再打开反馈框
function feedback() {
  hide()
  openFeedback()
}

function hide() {
  open.value = false
  document.body.style.overflow = ''
}

function onKey(e) {
  if (e.key === 'Escape' && open.value) hide()
}

watch(open, (v) => v && load())
onMounted(() => {
  load()
  addEventListener('keydown', onKey)
})
onBeforeUnmount(() => removeEventListener('keydown', onKey))
</script>

<template>
  <button
    type="button"
    class="btn-ghost btn-sm relative"
    :aria-label="hasNew ? '更新日志（有新版本）' : '更新日志'"
    title="更新日志"
    @click="show"
  >
    <Icon name="history" :size="17" /><span class="hidden sm:inline">更新日志</span>
    <span v-if="hasNew" class="absolute top-1 right-1 h-2 w-2 rounded-full bg-brand-2 ring-2 ring-white sm:top-1.5 sm:right-1.5" />
  </button>

  <Teleport to="body">
    <Transition name="sheet">
      <div v-if="open" class="fixed inset-0 z-[55]" role="dialog" aria-modal="true" aria-labelledby="changelog-title">
        <div class="absolute inset-0 bg-ink/20 backdrop-blur-[4px]" @click="hide" />
        <aside
          class="sheet-panel glass-strong absolute inset-x-0 bottom-0 max-h-[90vh] overflow-y-auto overscroll-contain rounded-t-[14px] shadow-[0_-24px_60px_-24px_rgb(11_47_122/0.45)] md:inset-y-0 md:right-0 md:left-auto md:max-h-none md:w-[520px] md:rounded-l-[14px] md:rounded-tr-none"
        >
          <div class="glass-strong sticky top-0 z-10 border-x-0 border-t-0 px-5 pt-3 pb-3 md:pt-5">
            <span class="mx-auto mb-2 block h-[5px] w-10 rounded-full bg-ink/15 md:hidden" />
            <div class="flex items-center gap-3">
              <span class="grid h-10 w-10 place-items-center rounded-2xl bg-brand text-white"><Icon name="history" :size="19" /></span>
              <div class="min-w-0 flex-1">
                <h2 id="changelog-title" class="text-lg font-bold">更新日志</h2>
                <p class="text-xs text-mute">当前版本 {{ data?.latest || '—' }}</p>
              </div>
              <!-- 反馈入口（v2.6.1 起从首页左下角移到这里，避免和对比面板重叠） -->
              <button class="flex h-10 shrink-0 cursor-pointer items-center gap-1.5 rounded-2xl bg-white/70 px-3.5 text-sm text-ink-2 transition-colors hover:bg-white hover:text-brand" @click="feedback">
                <Icon name="message" :size="16" />反馈
              </button>
              <button class="grid h-10 w-10 cursor-pointer place-items-center rounded-2xl bg-white/70 text-mute transition-transform duration-500 ease-out-expo hover:rotate-90" aria-label="关闭" @click="hide">
                <Icon name="x" :size="20" />
              </button>
            </div>
            <div class="scrollbar-none -mx-5 mt-3 flex gap-1.5 overflow-x-auto px-5">
              <button
                v-for="f in FILTERS"
                :key="f[0]"
                class="h-8 shrink-0 cursor-pointer rounded-full px-3 text-[13px] transition-colors duration-300"
                :class="filter === f[0] ? 'bg-brand text-white' : 'border border-edge bg-white/60 text-ink-2 hover:bg-white'"
                @click="filter = f[0]"
              >{{ f[1] }} <span class="tabular-nums opacity-75">{{ counts[f[0]] }}</span></button>
            </div>
          </div>

          <div class="px-5 pt-4 pb-10">

            <div v-if="!data" class="space-y-3"><div v-for="n in 3" :key="n" class="skeleton-bar h-24 rounded-2xl" /></div>

            <ol v-else class="relative ml-2 border-l-2 border-brand/15 pl-6">
              <li v-for="(r, ri) in releases" :key="r.version" v-reveal="ri" class="relative pb-7 last:pb-0">
                <span
                  class="absolute top-1 -left-[33px] grid h-4 w-4 place-items-center rounded-full ring-4 ring-white/80"
                  :class="ri === 0 && !filter ? 'bg-brand' : 'bg-brand/30'"
                />
                <div class="flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
                  <span class="text-base font-bold" :class="ri === 0 && !filter ? 'text-gradient' : ''">{{ r.version }}</span>
                  <time class="text-xs text-mute" :datetime="r.released_at">{{ formatTime(r.released_at) }}</time>
                  <span v-if="r.version === data.latest" class="tag bg-brand-soft text-brand">最新</span>
                </div>
                <ul class="mt-2.5 space-y-2">
                  <li v-for="e in r.entries" :key="e.id" class="group rounded-2xl border border-edge bg-white/60 p-3">
                    <div class="flex items-start gap-2">
                      <span class="tag shrink-0" :class="CAT_STYLE[e.category]?.[1]">
                        <Icon :name="CAT_STYLE[e.category]?.[2]" :size="12" />{{ CAT_STYLE[e.category]?.[0] }}
                      </span>
                      <p class="min-w-0 flex-1 text-[14.5px] font-semibold leading-snug">{{ e.title }}</p>
                    </div>
                    <p v-if="e.detail" class="mt-1.5 text-[13px] leading-relaxed text-ink-2">{{ e.detail }}</p>
                  </li>
                </ul>
              </li>
              <li v-if="!releases.length" class="py-6 text-sm text-mute">没有这类更新</li>
            </ol>
          </div>
        </aside>
      </div>
    </Transition>
  </Teleport>
</template>
