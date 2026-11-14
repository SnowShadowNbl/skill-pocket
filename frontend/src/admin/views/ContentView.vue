<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, formatStars, formatTime, isCancelled } from '../../api'
import Icon from '../../components/Icon.vue'
import { toast } from '../../composables/toast'
import AFilterBar from '../components/AFilterBar.vue'
import ABulkBar from '../components/ABulkBar.vue'
import ATable from '../components/ATable.vue'
import CoverQueuePanel from '../components/CoverQueuePanel.vue'
import ItemEditor from '../components/ItemEditor.vue'
import { runBulk } from '../composables/bulk'
import { askChoice } from '../composables/choice'
import { useDetailRoute } from '../composables/useDetailRoute'
import { useSelection } from '../composables/useSelection'
import { useQueryFilters } from '../composables/useQueryFilters'
import { REASONS } from '../reasons'

// 内容管理：所有收录过的条目（Skill、模型、工具……），点开在弹窗里查看全部数据并修改、删除，管理图片集
const route = useRoute()
const router = useRouter()
const { filters, params, activeCount, reset } = useQueryFilters({ q: '', status: '', kind: '', category: '', source: '', sort: 'collected', date_field: 'collected', date: { from: '', to: '' }, pinned: '', quality: '' })
const detail = useDetailRoute('id')
// 「条目」和「封面队列」两个视图（view=covers）
const view = computed(() => (route.query.view === 'covers' ? 'covers' : 'items'))
const setView = (v) => router.replace({ query: v === 'covers' ? { view: 'covers' } : {} })
const openId = computed(() => Number(detail.id.value) || null)
const page = ref(1)
const data = ref(null)
const tree = ref([])

const statusOptions = computed(() => [{ value: '', label: '全部状态' }, ...Object.entries(data.value?.statuses || {})
  .filter(([k]) => data.value?.counts?.[k]).map(([k, v]) => ({ value: k, label: `${v} ${data.value.counts[k]}` }))])
const kindOptions = computed(() => [{ value: '', label: '全部类型' }, ...Object.entries(data.value?.kinds || {}).map(([k, v]) => ({ value: k, label: v })), { value: 'none', label: '未分类型' }])
const catOptions = computed(() => [{ value: '', label: '全部分类' }, ...tree.value.flatMap((g) => [
  { value: g.code, label: `${g.name}（全部）`, group: g.name },
  ...g.children.map((c) => ({ value: c.code, label: c.name, group: g.name })),
])])
const sourceOptions = [{ value: '', label: '全部来源' }, { value: 'auto', label: '系统采集' }, { value: 'manual', label: '手动上传' }]
const sortOptions = [{ value: 'collected', label: '最新收录' }, { value: 'updated', label: '最近修改' }, { value: 'stars', label: '星标最多' }, { value: 'name', label: '按名称' }, { value: 'pinned', label: '置顶权重' }]
const dateFieldOptions = [{ value: 'collected', label: '按收录日期' }, { value: 'updated', label: '按修改日期' }]
const pinOptions = computed(() => [{ value: '', label: '全部条目' }, { value: '1', label: `只看置顶${data.value?.pinned_count ? ` ${data.value.pinned_count}` : ''}` }])
const fields = computed(() => [
  { key: 'q', type: 'search', label: '搜索条目', placeholder: '搜索名称、简介、仓库' },
  { key: 'status', type: 'select', label: '状态', options: statusOptions.value },
  { key: 'kind', type: 'select', label: '使用类型', options: kindOptions.value },
  { key: 'category', type: 'select', label: '分类', options: catOptions.value, searchable: true },
  { key: 'source', type: 'select', label: '来源', options: sourceOptions },
  { key: 'sort', type: 'select', label: '排序', options: sortOptions },
  { key: 'date_field', type: 'select', label: '日期类型', options: dateFieldOptions },
  { key: 'date', type: 'daterange', label: '全部日期', counts: true, fieldKey: 'date_field' },
  { key: 'pinned', type: 'select', label: '置顶', options: pinOptions.value },
])
const STATUS = { published: 'tag-ok', hidden: 'tag-gray', offline: 'tag-bad', awaiting: 'tag-blue', declined: 'tag-bad', pending_review: 'tag-warn', rejected: 'tag-gray', candidate: 'tag-gray' }
const columns = [
  { key: 'name', label: '条目', mobile: 'title' },
  { key: 'status', label: '状态', mobile: 'meta' },
  { key: 'kind', label: '类型 / 分类', hideBelow: 'md', mobile: 'sub' },
  { key: 'image_count', label: '图片', hideBelow: 'lg', mobile: 'hide' },
  { key: 'stars', label: '星标', mobile: 'meta', mlabel: true },
  { key: 'pin_weight', label: '置顶', hideBelow: 'md', mobile: 'meta' },
  { key: 'source', label: '来源', hideBelow: 'lg', mobile: 'hide' },
  { key: 'collected_at', label: '收录时间', align: 'right', mobile: 'hide' },
]

// 质量筛选：每个问题旁边显示数量，点一下加入筛选（多个同时满足）
const stats = ref(null)
async function loadStats() {
  try {
    stats.value = await api('/api/admin/items/quality-stats')
  } catch {}
}
const QUALITY_ORDER = ['no_cover', 'no_summary', 'no_install', 'source_broken', 'zero_fav', 'low_star', 'star_spike', 'rank_excluded']
const picked = computed(() => (filters.quality ? filters.quality.split(',') : []))
function toggleQuality(k) {
  const s = new Set(picked.value)
  s.has(k) ? s.delete(k) : s.add(k)
  filters.quality = QUALITY_ORDER.filter((x) => s.has(x)).join(',')
}
const qualityLabel = (k) => data.value?.qualities?.[k] || stats.value?.items?.[k]?.label || k

// 勾选与批量操作
const sel = useSelection({ rows: computed(() => data.value?.items || []), total: computed(() => data.value?.total || 0), params })
const bulk = (action) => (scope, reason, params) => runBulk('/api/admin/items/bulk', { action, scope, reason, params })
const leafCats = computed(() => tree.value.flatMap((g) => g.children.map((c) => ({ value: c.id, label: c.name, group: g.name }))))
const bulkActions = [
  { key: 'set_category', label: '改分类', icon: 'layers',
    pick: (n) => askChoice({ title: '批量改分类', impact: `将修改 ${n} 个条目的分类，并锁定分类（重新提炼时不再覆盖）`, options: leafCats.value, placeholder: '选择目标分类', okText: '修改' }).then((v) => (v == null ? null : { category_id: v })),
    run: bulk('set_category') },
  { key: 'hide', label: '下线', icon: 'lock', danger: true,
    reason: { title: '批量下线条目', impact: (n) => `将隐藏 ${n} 个条目，前台不再显示`, templates: REASONS.contentHide, okText: '下线' }, run: bulk('hide') },
  { key: 'reextract', label: '重新提炼', icon: 'refresh',
    confirm: (n) => ({ title: `重新提炼 ${n} 个条目？`, message: 'AI 会重新整理简介和安装说明，人工改过的字段会保留。进度在右下角任务栏。', okText: '重新提炼' }), run: bulk('reextract') },
  { key: 'cover', label: '补封面', icon: 'image',
    confirm: (n) => ({ title: `给 ${n} 个条目补封面？`, message: '只给没有封面的条目生成；已有封面、人工设置过的会跳过。', okText: '补封面' }), run: bulk('cover') },
  { key: 'show', label: '恢复上线', icon: 'check', more: true,
    reason: { title: '批量恢复上线', impact: (n) => `将恢复 ${n} 个条目，前台重新显示`, templates: REASONS.contentShow, okText: '恢复上线' }, run: bulk('show') },
  { key: 'rank_exclude', label: '排除出榜单', icon: 'alert', more: true, danger: true,
    reason: { title: '批量排除出榜单', impact: (n) => `${n} 个条目将不再出现在榜单里（仍可搜索和访问），日榜、周榜立即重算`, templates: REASONS.rankExclude, okText: '排除' }, run: bulk('rank_exclude') },
  { key: 'rank_include', label: '恢复进榜单', icon: 'check', more: true,
    reason: { title: '批量恢复进榜单', impact: (n) => `${n} 个条目将重新参与榜单排名`, templates: REASONS.rankInclude, okText: '恢复' }, run: bulk('rank_include') },
]
function afterBulk() {
  load()
  loadStats()
}

async function load(more = false) {
  page.value = more ? page.value + 1 : 1
  const p = new URLSearchParams(params.value)
  p.set('page', page.value)
  try {
    const d = await api(`/api/admin/items?${p}`)
    data.value = more ? { ...d, items: [...data.value.items, ...d.items] } : d
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  }
}
watch(() => params.value.toString(), () => load(), { immediate: true })

// 弹窗里改了 / 删了：刷新列表里这一行
function onChanged(row) {
  if (!data.value) return
  const i = data.value.items.findIndex((x) => x.id === row?.id)
  if (row?.deleted) {
    if (i >= 0) data.value.items.splice(i, 1)
    data.value.total--
  } else if (i >= 0) {
    data.value.items[i] = { ...data.value.items[i], ...row }
  }
}

const rangeText = computed(() => {
  const { from, to } = filters.date
  return from ? `${from === to ? from : `${from} ~ ${to}`}${filters.date_field === 'collected' ? '收录' : '修改'}` : ''
})

onMounted(async () => {
  // 其他页面用 ?day=2026-11-01 跳过来：当作这一天的日期区间
  if (route.query.day) {
    const { day, ...rest } = route.query
    await router.replace({ query: rest })
    filters.date = { from: String(day), to: String(day) }
  }
  try {
    tree.value = await api('/api/categories')
  } catch {}
  loadStats()
})
</script>

<template>
  <div>
    <div class="mb-5 flex flex-wrap items-center gap-3">
      <h1 class="m-0 text-xl font-semibold">内容管理</h1>
      <div class="seg ml-auto"><button :class="{ on: view === 'items' }" @click="setView('items')">条目</button><button :class="{ on: view === 'covers' }" @click="setView('covers')">封面队列</button></div>
    </div>

    <CoverQueuePanel v-if="view === 'covers'" />
    <section v-else class="card">
      <AFilterBar :filters="filters" :fields="fields" :active-count="activeCount" @reset="reset" />
      <div v-if="stats" class="flex flex-wrap items-center gap-1.5 border-b border-line px-3.5 py-2.5">
        <button
          v-for="k in QUALITY_ORDER.filter((x) => stats.items[x])"
          :key="k"
          type="button"
          class="flex h-8 items-center gap-1.5 rounded-full border px-3 text-[12.5px] transition-colors"
          :class="picked.includes(k) ? 'border-primary bg-primary-soft font-medium text-primary' : 'border-line bg-white text-ink-2 hover:border-primary hover:text-primary'"
          :aria-pressed="picked.includes(k)"
          @click="toggleQuality(k)"
        >{{ stats.items[k].label }}<b class="tabular-nums" :class="picked.includes(k) ? '' : stats.items[k].count ? 'text-warn' : 'text-mute'">{{ stats.items[k].count }}</b></button>
      </div>
      <ATable :columns="columns" :rows="data?.items || []" :loading="!data" :selection="sel" clickable empty-text="没有符合条件的条目" @row-click="(it) => detail.open(it.id)">
        <template #cell-name="{ row: it }">
          <span class="flex items-center gap-3">
            <span class="h-10 w-14 shrink-0 overflow-hidden rounded-md border border-line bg-subtle">
              <img v-if="it.cover_url" :src="it.cover_url" alt="" class="h-full w-full object-cover" loading="lazy" />
            </span>
            <span class="min-w-0">
              <b class="block max-w-[260px] truncate font-semibold">{{ it.name }}</b>
              <span class="block max-w-[260px] truncate text-xs text-mute">{{ it.repo ? it.repo + (it.sub_path ? '/' + it.sub_path : '') : it.summary }}</span>
              <span v-if="it.quality?.length || it.rank_excluded" class="mt-0.5 flex flex-wrap gap-1">
                <span v-for="k in (it.quality || []).filter((x) => x !== 'rank_excluded').slice(0, 3)" :key="k" class="tag tag-warn !h-[18px] !px-1.5 !text-[11px]">{{ qualityLabel(k) }}</span>
                <span v-if="it.rank_excluded" class="tag tag-bad !h-[18px] !px-1.5 !text-[11px]" :title="it.rank_excluded.reason">已排除榜单</span>
              </span>
            </span>
          </span>
        </template>
        <template #cell-status="{ row: it }"><span class="tag" :class="STATUS[it.status] || 'tag-gray'">{{ it.status_label }}</span></template>
        <template #cell-kind="{ row: it }"><span class="text-[13px]">{{ it.kind?.name || '—' }}</span><span class="ml-1.5 text-xs text-mute sm:ml-0 sm:block">{{ it.category }}</span></template>
        <template #cell-image_count="{ row: it }"><span class="flex items-center gap-1 tabular-nums text-ink-2"><Icon name="image" :size="13" />{{ it.image_count }}</span></template>
        <template #cell-stars="{ row: it }"><span class="tabular-nums">{{ it.stars != null ? formatStars(it.stars) : '—' }}</span></template>
        <template #cell-pin_weight="{ row: it }"><span v-if="it.pin_weight" class="tag tag-blue" :title="`首页置顶权重 ${it.pin_weight}`">置顶 {{ it.pin_weight }}</span><span v-else class="hidden text-mute sm:inline">—</span></template>
        <template #cell-source="{ row: it }"><span class="text-xs">{{ it.source === 'auto' ? '系统采集' : it.uploader ? `${it.uploader} 上传` : '手动上传' }}</span></template>
        <template #cell-collected_at="{ row: it }"><span class="text-xs whitespace-nowrap text-mute">{{ formatTime(it.collected_at, false) }}</span></template>
      </ATable>
      <div v-if="data" class="flex items-center border-t border-line px-[18px] py-3 text-xs text-mute">
        共 {{ data.total }} 个条目<template v-if="!filters.status && data.counts?.published != null">（已发布 {{ data.counts.published }}）</template><template v-if="rangeText">（{{ rangeText }}）</template>
        <button v-if="data.items.length < data.total" class="btn btn-sm ml-auto" @click="load(true)">加载更多</button>
      </div>
    </section>

    <ABulkBar v-if="view === 'items'" :selection="sel" :actions="bulkActions" noun="个条目" @done="afterBulk" />
    <ItemEditor v-if="openId" :id="openId" :tree="tree" :kinds="data?.kinds || {}" @close="detail.close()" @changed="onChanged" />
  </div>
</template>
