<script setup>
import { computed, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { api, formatTime, isCancelled } from '../../api'
import { toast } from '../../composables/toast'
import ADrawer from '../components/ADrawer.vue'
import AFilterBar from '../components/AFilterBar.vue'
import ATable from '../components/ATable.vue'
import { onActionError } from '../composables/handled'
import { askReason } from '../composables/reason'
import { reasonTemplates } from '../composables/useReasonTemplates'
import { useDetailRoute } from '../composables/useDetailRoute'
import { useQueryFilters } from '../composables/useQueryFilters'
import { REASONS } from '../reasons'

// 分享页管理：用户公开分享的收藏夹。可以预览内容、关闭（关闭后链接失效，用户也不能再开启）、解除关闭
const { filters, params, activeCount, reset } = useQueryFilters({ q: '', status: '', owner_id: '' })
const detail = useDetailRoute('id')
const data = ref(null)
const page = ref(1)
const preview = ref(null)
const busy = ref(0)

const statusOptions = [{ value: '', label: '全部状态' }, { value: 'sharing', label: '分享中' }, { value: 'closed', label: '已关闭' }]
const fields = [
  { key: 'q', type: 'search', label: '搜索分享', placeholder: '搜索分类名、分享人' },
  { key: 'status', type: 'select', label: '状态', options: statusOptions },
]
const columns = [
  { key: 'name', label: '收藏夹', mobile: 'title' },
  { key: 'owner', label: '分享人', mobile: 'sub' },
  { key: 'count', label: '条目', align: 'right', mobile: 'meta', mlabel: true },
  { key: 'views', label: '访问', align: 'right', mobile: 'meta', mlabel: true },
  { key: 'status', label: '状态', mobile: 'meta' },
  { key: 'created_at', label: '开启时间', hideBelow: 'lg', mobile: 'hide' },
  { key: 'actions', label: '', align: 'right', mobile: 'hide' },
]

async function load(more = false) {
  page.value = more ? page.value + 1 : 1
  const p = new URLSearchParams(params.value)
  p.set('page', page.value)
  p.set('page_size', 30)
  try {
    const d = await api(`/api/admin/shares?${p}`)
    data.value = more ? { ...d, items: [...data.value.items, ...d.items] } : d
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  }
}
watch(() => params.value.toString(), () => load(), { immediate: true })

watch(detail.id, async (id) => {
  preview.value = null
  if (!id) return
  try {
    preview.value = await api(`/api/admin/shares/${id}/preview`)
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
    detail.close()
  }
}, { immediate: true })

async function setClosed(s, close) {
  const reason = await askReason({
    title: close ? `关闭「${s.name}」的分享？` : `解除「${s.name}」的关闭？`,
    impact: close ? '公开链接立即失效，分享人也不能再开启分享' : '分享人可以再次开启分享；原链接恢复',
    templates: close ? await reasonTemplates('share_close', REASONS.shareClose) : ['核实后内容没有问题', '分享人申诉通过'],
    danger: close,
    okText: close ? '关闭分享' : '解除关闭',
  })
  if (reason === null) return
  busy.value = s.id
  try {
    const r = await api(`/api/admin/shares/${s.id}/${close ? 'close' : 'reopen'}`, { method: 'POST', body: { reason, expected_status: s.status } })
    toast(close ? '已关闭分享' : r.status === 'private' ? '分享人已取消分享，这条已从列表移除' : '已解除关闭', 'success')
    await load()
    if (preview.value?.share.id === s.id) preview.value = await api(`/api/admin/shares/${s.id}/preview`).catch(() => null)
  } catch (e) {
    await onActionError(e, load)
  } finally {
    busy.value = 0
  }
}
const viewsText = (v) => (v == null ? '未知' : v)
const counts = computed(() => data.value?.counts)
</script>

<template>
  <div>
    <h1 class="m-0 mb-5 text-xl font-semibold">分享页</h1>
    <section class="card">
      <AFilterBar :filters="filters" :fields="fields" :active-count="activeCount" @reset="reset" />
      <p v-if="filters.owner_id" class="m-0 flex items-center gap-2 border-b border-line bg-primary-soft px-[18px] py-2 text-[13px] text-primary">
        只看用户 #{{ filters.owner_id }} 的分享<button class="ml-auto underline" @click="filters.owner_id = ''">看全部</button>
      </p>
      <ATable :columns="columns" :rows="data?.items || []" :loading="!data" clickable empty-text="没有符合条件的分享" @row-click="(s) => detail.open(s.id)">
        <template #cell-name="{ row: s }"><b class="font-semibold">{{ s.emoji }} {{ s.name }}</b><span class="ml-1.5 text-xs text-mute">{{ s.dimension }}</span></template>
        <template #cell-owner="{ row: s }"><RouterLink :to="{ path: '/users', query: { id: s.owner.id } }" class="hover:text-primary" @click.stop>{{ s.owner.label }}</RouterLink></template>
        <template #cell-count="{ row: s }"><span class="tabular-nums">{{ s.count }}</span></template>
        <template #cell-views="{ row: s }"><span class="tabular-nums" :class="s.views == null ? 'text-mute' : ''">{{ viewsText(s.views) }}</span></template>
        <template #cell-status="{ row: s }">
          <span class="tag" :class="s.status === 'sharing' ? 'tag-ok' : 'tag-bad'">{{ s.status_label }}</span>
        </template>
        <template #cell-created_at="{ row: s }"><span class="text-xs whitespace-nowrap text-mute">{{ formatTime(s.created_at, false) }}</span></template>
        <template #cell-actions="{ row: s }">
          <button v-if="s.status === 'sharing'" class="btn btn-sm btn-danger" :disabled="busy === s.id" @click.stop="setClosed(s, true)">关闭</button>
          <button v-else class="btn btn-sm" :disabled="busy === s.id" @click.stop="setClosed(s, false)">解除关闭</button>
        </template>
      </ATable>
      <div v-if="data" class="flex items-center border-t border-line px-[18px] py-3 text-xs text-mute">
        共 {{ data.total }} 条<template v-if="counts"> · 分享中 {{ counts.sharing }} · 已关闭 {{ counts.closed }}</template>
        <button v-if="data.items.length < data.total" class="btn btn-sm ml-auto" @click="load(true)">加载更多</button>
      </div>
    </section>

    <ADrawer :open="!!detail.id.value" label="分享预览" @close="detail.close()">
      <template #header>
        <p v-if="!preview" class="m-0 text-mute">加载中…</p>
        <div v-else>
          <p class="m-0 font-semibold">{{ preview.share.emoji }} {{ preview.share.name }}<span class="tag ml-2" :class="preview.share.status === 'sharing' ? 'tag-ok' : 'tag-bad'">{{ preview.share.status_label }}</span></p>
          <p class="m-0 truncate text-xs text-mute">{{ preview.share.owner.label }} · {{ preview.share.count }} 个条目 · 访问 {{ viewsText(preview.share.views) }}</p>
        </div>
      </template>
      <div v-if="!preview" class="skeleton h-60" />
      <template v-else>
        <p v-if="preview.share.closed" class="m-0 mb-3 rounded-lg bg-bad-soft px-3 py-2 text-[13px] text-bad">
          {{ preview.share.closed.by?.label || '管理员' }} 于 {{ formatTime(preview.share.closed.at) }} 关闭<template v-if="preview.share.closed.reason">：{{ preview.share.closed.reason }}</template>
        </p>
        <p v-if="!preview.items.length" class="empty">这个收藏夹里没有条目</p>
        <ul class="m-0 list-none p-0">
          <li v-for="i in preview.items" :key="i.id" class="border-b border-dashed border-line py-2.5 text-[13px] last:border-0">
            <span class="flex items-center gap-2">
              <RouterLink :to="{ path: '/content', query: { id: i.id } }" class="min-w-0 flex-1 truncate font-medium hover:text-primary">{{ i.name }}</RouterLink>
              <span v-if="i.category" class="tag tag-gray">{{ i.category.name }}</span>
              <span v-if="i.status !== 'published'" class="tag tag-warn">未上线</span>
            </span>
            <span v-if="i.summary" class="mt-0.5 block text-xs text-ink-2">{{ i.summary }}</span>
          </li>
        </ul>
      </template>
      <template v-if="preview" #footer>
        <div class="flex items-center gap-2">
          <RouterLink :to="{ path: '/users', query: { id: preview.share.owner.id } }" class="btn">分享人</RouterLink>
          <button v-if="preview.share.status === 'sharing'" class="btn btn-danger ml-auto" :disabled="busy === preview.share.id" @click="setClosed(preview.share, true)">关闭分享</button>
          <button v-else class="btn ml-auto" :disabled="busy === preview.share.id" @click="setClosed(preview.share, false)">解除关闭</button>
        </div>
      </template>
    </ADrawer>
  </div>
</template>
