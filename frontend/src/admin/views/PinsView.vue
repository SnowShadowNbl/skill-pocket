<script setup>
import { computed, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { api, isCancelled } from '../../api'
import { toast } from '../../composables/toast'
import APinDialog from '../components/APinDialog.vue'
import ATable from '../components/ATable.vue'
import { toBj } from '../composables/time'

// 推荐位：首页置顶的条目与排期。生效中 / 未开始 / 已结束，到期自动失效
const route = useRoute()
const router = useRouter()
const TABS = [['', '全部'], ['active', '生效中'], ['scheduled', '未开始'], ['expired', '已结束']]
const state = computed(() => (TABS.some((t) => t[0] === route.query.state) ? route.query.state || '' : ''))
const setState = (s) => router.replace({ query: { state: s || undefined } })
const data = ref(null)
const counts = ref(null)
const editing = ref(null)

async function load() {
  try {
    const d = await api(`/api/admin/pins${state.value ? `?state=${state.value}` : ''}`)
    data.value = d
    if (d.counts) counts.value = d.counts
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  }
}
watch(state, load, { immediate: true })
const total = computed(() => (counts.value ? counts.value.active + counts.value.scheduled + counts.value.expired : null))
const PIN_TAG = { active: 'tag-blue', scheduled: 'tag-warn', expired: 'tag-gray' }
const columns = [
  { key: 'name', label: '条目', mobile: 'title' },
  { key: 'state', label: '状态', mobile: 'meta' },
  { key: 'weight', label: '权重', align: 'right', mobile: 'meta', mlabel: true },
  { key: 'window', label: '排期（北京时间）', mobile: 'sub' },
  { key: 'actions', label: '', align: 'right', mobile: 'action' },
]

// 剩余 / 距开始的时间描述
function span(ms) {
  const m = Math.round(ms / 60000)
  if (m < 60) return `${Math.max(m, 1)} 分钟`
  if (m < 1440) return `${Math.round(m / 60)} 小时`
  return `${Math.round(m / 1440)} 天`
}
function hint(p) {
  if (p.state === 'active' && p.ends_at) return `还剩 ${span(new Date(p.ends_at) - Date.now())}`
  if (p.state === 'scheduled' && p.starts_at) return `${span(new Date(p.starts_at) - Date.now())}后开始`
  return ''
}
const windowText = (p) => (p.starts_at || p.ends_at ? `${toBj(p.starts_at) || '立即'} ~ ${toBj(p.ends_at) || '不限'}` : '长期')
</script>

<template>
  <div>
    <h1 class="m-0 mb-5 text-xl font-semibold">推荐位</h1>
    <section class="card">
      <div class="flex flex-wrap items-center gap-2 border-b border-line px-3.5 py-3">
        <div class="seg">
          <button v-for="t in TABS" :key="t[0]" :class="{ on: state === t[0] }" @click="setState(t[0])">
            {{ t[1] }}<b v-if="counts && (t[0] ? counts[t[0]] : total)" class="ml-1 tabular-nums" :class="state === t[0] ? '' : 'text-mute'">{{ t[0] ? counts[t[0]] : total }}</b>
          </button>
        </div>
        <RouterLink :to="{ path: '/content', query: { sort: 'pinned' } }" class="btn ml-auto">去内容管理添加</RouterLink>
      </div>
      <ATable :columns="columns" :rows="data?.items || []" :loading="!data" empty-text="还没有推荐位">
        <template #cell-name="{ row: i }">
          <RouterLink :to="{ path: '/content', query: { id: i.id } }" class="font-semibold text-ink no-underline hover:text-primary">{{ i.name }}</RouterLink>
          <span class="block max-w-[320px] truncate text-xs text-mute">{{ i.repo }}</span>
        </template>
        <template #cell-state="{ row: i }">
          <span class="tag" :class="PIN_TAG[i.pin.state]">{{ i.pin.state_label }}</span>
          <span v-if="hint(i.pin)" class="ml-1.5 text-xs text-mute">{{ hint(i.pin) }}</span>
        </template>
        <template #cell-weight="{ row: i }"><b class="tabular-nums">{{ i.pin.weight }}</b></template>
        <template #cell-window="{ row: i }"><span class="text-xs whitespace-nowrap tabular-nums text-ink-2">{{ windowText(i.pin) }}</span></template>
        <template #cell-actions="{ row: i }"><button class="btn btn-sm" @click="editing = i">调整</button></template>
      </ATable>
    </section>
    <APinDialog :open="!!editing" :item="editing" @close="editing = null" @saved="load" />
  </div>
</template>
