<script setup>
import { computed, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { api, formatTime, isCancelled } from '../../api'
import { toast } from '../../composables/toast'
import ABulkBar from '../components/ABulkBar.vue'
import ADrawer from '../components/ADrawer.vue'
import AFilterBar from '../components/AFilterBar.vue'
import ATable from '../components/ATable.vue'
import { runBulk } from '../composables/bulk'
import { onActionError } from '../composables/handled'
import { askReason } from '../composables/reason'
import { useDetailRoute } from '../composables/useDetailRoute'
import { useQueryFilters } from '../composables/useQueryFilters'
import { useSelection } from '../composables/useSelection'

// 收录任务：用户的查找、截图识别、提交后的提炼，以及后台提炼任务。看卡在哪一步、为什么失败，失败 / 卡住的可以重试或终止
const { filters, params, activeCount, reset } = useQueryFilters({ q: '', kind: '', task_kind: '', status: '', user_id: '', created: { from: '', to: '' } })
const detail = useDetailRoute('id')
const data = ref(null)
const page = ref(1)
const current = ref(null)
const busy = ref(false)

const STATUS_TABS = [['', '全部'], ['running', '进行中'], ['stuck', '卡住'], ['failed', '失败'], ['done', '完成']]
const kindOptions = computed(() => [{ value: '', label: '全部类型' }, ...Object.entries(data.value?.kinds || {}).map(([k, v]) => ({ value: k, label: v }))])
const fields = computed(() => [
  { key: 'q', type: 'search', label: '搜索任务', placeholder: '搜索标题或用户' },
  { key: 'kind', type: 'select', label: '类型', options: kindOptions.value },
  ...(data.value?.task_kinds ? [{ key: 'task_kind', type: 'select', label: '后台任务类型', options: [{ value: '', label: '全部后台任务' }, ...Object.entries(data.value.task_kinds).map(([k, v]) => ({ value: k, label: v }))] }] : []),
  { key: 'created', type: 'daterange', label: '提交日期' },
])
const columns = [
  { key: 'title', label: '任务', mobile: 'title' },
  { key: 'kind', label: '类型', hideBelow: 'md', mobile: 'meta' },
  { key: 'user', label: '提交人', hideBelow: 'lg', mobile: 'sub' },
  { key: 'status', label: '状态', mobile: 'meta' },
  { key: 'duration', label: '耗时', hideBelow: 'md', mobile: 'meta' },
  { key: 'created_at', label: '提交时间', align: 'right', mobile: 'hide' },
]
const sel = useSelection({ rows: computed(() => data.value?.items || []), total: computed(() => data.value?.total || 0), params, selectable: (t) => !!t.can_retry })

async function load(more = false) {
  page.value = more ? page.value + 1 : 1
  const p = new URLSearchParams(params.value)
  p.set('page', page.value)
  p.set('page_size', 30)
  try {
    const d = await api(`/api/admin/ingest-tasks?${p}`)
    data.value = more ? { ...d, items: [...data.value.items, ...d.items] } : d
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  }
}
watch(() => params.value.toString(), () => load(), { immediate: true })

async function loadDetail(id) {
  try {
    const d = await api(`/api/admin/ingest-tasks/${encodeURIComponent(id)}`)
    if (detail.id.value === id) current.value = d
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
    detail.close()
  }
}
watch(detail.id, (id) => {
  current.value = null
  if (id) loadDetail(id)
}, { immediate: true })

const dur = (s) => (s == null ? '—' : s < 60 ? `${s} 秒` : s < 3600 ? `${Math.floor(s / 60)} 分 ${s % 60} 秒` : `${Math.floor(s / 3600)} 小时 ${Math.floor((s % 3600) / 60)} 分`)
const stateOf = (t) => (t.stuck ? ['卡住', 'tag-warn'] : t.status === 'failed' ? ['失败', 'tag-bad'] : t.status === 'running' ? ['进行中', 'tag-blue'] : ['完成', 'tag-ok'])
const STAGE = { done: 'tag-ok', success: 'tag-ok', failed: 'tag-bad', error: 'tag-bad', running: 'tag-blue' }
const LEVEL = { error: 'text-bad', warn: 'text-warn', warning: 'text-warn' }

async function refresh() {
  await load()
  if (detail.id.value) await loadDetail(detail.id.value)
}
async function retry(t) {
  const reason = await askReason({
    title: `重试「${t.title}」？`,
    impact: '会用同样的输入另起一个新任务，原任务保持原样',
    templates: ['网络或接口临时失败', '问题已修复，重新执行'],
    okText: '重试',
  })
  if (reason === null) return
  busy.value = true
  try {
    const r = await api(`/api/admin/ingest-tasks/${encodeURIComponent(t.id)}/retry`, { method: 'POST', body: { reason, expected_status: t.status } })
    toast(r.new_task_id ? `已另起任务 ${r.new_task_id}${r.count ? `（${r.count} 项）` : ''}${r.skipped_done ? `，跳过已完成的 ${r.skipped_done} 项` : ''}` : '已重试', 'success')
    await refresh()
  } catch (e) {
    await onActionError(e, refresh)
  } finally {
    busy.value = false
  }
}
// 只重试失败的条目，已成功的不动（后台任务才有）
async function retryFailed(t) {
  const reason = await askReason({
    title: `只重试「${t.title}」里失败的条目？`,
    impact: '成功的条目不会重做，也不会重复消耗 AI；会另起一个新任务',
    templates: ['网络或接口临时失败', '问题已修复，重新执行'],
    okText: '重试失败项',
  })
  if (reason === null) return
  busy.value = true
  try {
    const r = await api(`/api/admin/ingest-tasks/${encodeURIComponent(t.id)}/retry-failed`, { method: 'POST', body: { reason, expected_status: t.status } })
    toast(`已另起任务 ${r.new_task_id}：重试 ${r.retried} 项，跳过已完成的 ${r.skipped_done} 项`, 'success')
    await refresh()
  } catch (e) {
    await onActionError(e, refresh)
  } finally {
    busy.value = false
  }
}
async function abort(t) {
  const reason = await askReason({
    title: `终止「${t.title}」？`,
    impact: '任务会被标成失败；后台线程不一定立刻停下',
    templates: ['任务卡住，手动终止', '输入有误，重新提交'],
    danger: true,
    okText: '终止',
  })
  if (reason === null) return
  busy.value = true
  try {
    await api(`/api/admin/ingest-tasks/${encodeURIComponent(t.id)}/abort`, { method: 'POST', body: { reason, expected_status: t.status } })
    toast('已终止', 'success')
    await refresh()
  } catch (e) {
    await onActionError(e, refresh)
  } finally {
    busy.value = false
  }
}
const bulkActions = [
  { key: 'retry', label: '批量重试', icon: 'refresh',
    reason: { title: '批量重试任务', impact: (n) => `将为 ${n} 个失败 / 卡住的任务另起新任务`, templates: ['网络或接口临时失败', '问题已修复，重新执行'], okText: '重试' },
    run: (scope, reason) => {
      if (!scope.ids) throw new Error('批量重试请逐页勾选，一次最多 50 个')
      return runBulk('/api/admin/ingest-tasks/bulk', { action: 'retry', scope, reason })
    } },
]
</script>

<template>
  <div>
    <h1 class="m-0 mb-5 text-xl font-semibold">收录任务</h1>
    <section class="card">
      <div class="flex flex-wrap items-center gap-2 border-b border-line px-3.5 py-3">
        <div class="seg">
          <button v-for="t in STATUS_TABS" :key="t[0]" :class="{ on: filters.status === t[0] }" @click="filters.status = t[0]">
            {{ t[1] }}<b v-if="data && t[0] && data.counts[t[0]]" class="ml-1 tabular-nums" :class="filters.status === t[0] ? '' : t[0] === 'failed' ? 'text-bad' : t[0] === 'stuck' ? 'text-warn' : 'text-mute'">{{ data.counts[t[0]] }}</b>
          </button>
        </div>
      </div>
      <AFilterBar :filters="filters" :fields="fields" :active-count="activeCount - (filters.status ? 1 : 0)" @reset="reset" />
      <p v-if="filters.user_id" class="m-0 flex items-center gap-2 border-b border-line bg-primary-soft px-[18px] py-2 text-[13px] text-primary">
        只看用户 #{{ filters.user_id }} 的任务<button class="ml-auto underline" @click="filters.user_id = ''">看全部</button>
      </p>
      <ATable :columns="columns" :rows="data?.items || []" :loading="!data" :selection="sel" clickable empty-text="没有符合条件的任务" @row-click="(t) => detail.open(t.id)">
        <template #cell-title="{ row: t }">
          <b class="block max-w-[340px] truncate font-semibold">{{ t.title }}</b>
          <span v-if="t.error" class="block max-w-[340px] truncate text-xs text-bad">{{ t.error }}</span>
          <span v-else class="block max-w-[340px] truncate text-xs text-mute">{{ t.stage_label }}</span>
        </template>
        <template #cell-kind="{ row: t }"><span class="tag tag-gray">{{ t.kind_label }}</span></template>
        <template #cell-user="{ row: t }"><span class="text-[13px]">{{ t.user?.label || '系统' }}</span></template>
        <template #cell-status="{ row: t }"><span class="tag" :class="stateOf(t)[1]">{{ stateOf(t)[0] }}</span></template>
        <template #cell-duration="{ row: t }"><span class="text-xs tabular-nums text-ink-2">{{ dur(t.duration_s) }}</span></template>
        <template #cell-created_at="{ row: t }"><span class="text-xs whitespace-nowrap text-mute">{{ formatTime(t.created_at) }}</span></template>
      </ATable>
      <div v-if="data" class="flex items-center border-t border-line px-[18px] py-3 text-xs text-mute">
        共 {{ data.total }} 个任务
        <button v-if="data.items.length < data.total" class="btn btn-sm ml-auto" @click="load(true)">加载更多</button>
      </div>
    </section>
    <ABulkBar :selection="sel" :actions="bulkActions" noun="个任务" @done="refresh" />

    <ADrawer :open="!!detail.id.value" label="任务详情" :width="640" @close="detail.close()">
      <template #header>
        <p v-if="!current" class="m-0 text-mute">加载中…</p>
        <div v-else>
          <p class="m-0 truncate font-semibold">{{ current.title }}<span class="tag ml-2" :class="stateOf(current)[1]">{{ stateOf(current)[0] }}</span></p>
          <p class="m-0 truncate text-xs text-mute">{{ current.kind_label }} · {{ current.id }}</p>
        </div>
      </template>
      <div v-if="!current" class="skeleton h-72" />
      <template v-else>
        <dl class="m-0 grid grid-cols-[76px_1fr] gap-x-3 gap-y-2 text-[13px]">
          <dt class="text-mute">提交人</dt><dd class="m-0"><RouterLink v-if="current.user" :to="{ path: '/users', query: { id: current.user.id } }" class="text-primary hover:underline">{{ current.user.label }}</RouterLink><template v-else>系统</template></dd>
          <dt class="text-mute">当前环节</dt><dd class="m-0">{{ current.stage_label }}</dd>
          <dt class="text-mute">提交时间</dt><dd class="m-0">{{ formatTime(current.created_at) }}</dd>
          <dt class="text-mute">耗时</dt><dd class="m-0">{{ dur(current.duration_s) }}</dd>
          <template v-if="current.progress"><dt class="text-mute">进度</dt><dd class="m-0 tabular-nums">{{ current.progress.done }} / {{ current.progress.total }}<template v-if="current.progress.failed">，失败 {{ current.progress.failed }}</template></dd></template>
          <template v-if="current.item"><dt class="text-mute">关联条目</dt><dd class="m-0"><RouterLink :to="{ path: '/content', query: { id: current.item.id } }" class="text-primary hover:underline">{{ current.item.name }}</RouterLink></dd></template>
        </dl>
        <p v-if="current.error" class="m-0 mt-3 rounded-lg bg-bad-soft px-3 py-2 text-[13px] break-words text-bad">{{ current.error }}</p>

        <h3 class="mt-5 mb-2 text-[13px] font-semibold">环节</h3>
        <p v-if="!current.stages?.length" class="m-0 text-[13px] text-mute">没有环节记录</p>
        <ol class="m-0 list-none p-0">
          <li v-for="(s, i) in current.stages" :key="i" class="flex items-start gap-2.5 border-b border-dashed border-line py-2 text-[13px] last:border-0">
            <span class="tag mt-0.5 shrink-0" :class="STAGE[s.status] || 'tag-gray'">{{ s.label }}</span>
            <span class="min-w-0 flex-1 break-words text-ink-2">{{ s.message || '—' }}</span>
            <span class="shrink-0 text-xs text-mute tabular-nums">{{ s.duration_s != null ? dur(s.duration_s) : '' }}</span>
          </li>
        </ol>

        <!-- 查找 -->
        <template v-if="current.kind === 'finder' && current.extra">
          <h3 class="mt-5 mb-2 text-[13px] font-semibold">查找详情</h3>
          <dl class="m-0 grid grid-cols-[76px_1fr] gap-x-3 gap-y-2 text-[13px]">
            <dt class="text-mute">方式</dt><dd class="m-0">{{ current.extra.mode === 'text' ? '长文识别' : '搜索添加' }}</dd>
            <dt class="text-mute">查询</dt><dd class="m-0 break-words whitespace-pre-wrap">{{ current.extra.query }}</dd>
            <template v-if="current.extra.source_url"><dt class="text-mute">来源</dt><dd class="m-0 break-all"><a :href="current.extra.source_url" target="_blank" rel="noopener noreferrer" class="text-primary hover:underline">{{ current.extra.source_url }}</a></dd></template>
            <dt class="text-mute">候选</dt><dd class="m-0 tabular-nums">{{ current.extra.candidates }} 个，已导入 {{ current.extra.imported }} 个</dd>
            <template v-if="current.extra.message"><dt class="text-mute">结果</dt><dd class="m-0 break-words">{{ current.extra.message }}</dd></template>
          </dl>
        </template>

        <!-- 截图识别 -->
        <template v-else-if="current.kind === 'screenshot' && current.extra">
          <h3 class="mt-5 mb-2 text-[13px] font-semibold">截图</h3>
          <a v-if="current.extra.image_url" :href="current.extra.image_url" target="_blank" rel="noopener noreferrer"><img :src="current.extra.image_url" alt="用户上传的截图" class="max-h-72 max-w-full rounded-lg border border-line object-contain" loading="lazy" /></a>
          <p v-if="current.extra.error" class="m-0 mt-2 text-[13px] text-bad">{{ current.extra.error }}</p>
          <ul v-if="current.extra.items?.length" class="m-0 mt-3 list-none p-0">
            <li v-for="(x, i) in current.extra.items" :key="i" class="flex flex-wrap items-center gap-x-2 gap-y-0.5 border-b border-dashed border-line py-2 text-[13px] last:border-0">
              <b class="font-medium">{{ x.name }}</b><span class="text-xs text-mute">{{ x.full_name }}</span>
              <span class="tag tag-gray">{{ x.state }}</span><span v-if="x.confidence != null" class="text-xs text-mute tabular-nums">把握 {{ Math.round(x.confidence * 100) }}%</span>
              <RouterLink v-if="x.item_id" :to="{ path: '/content', query: { id: x.item_id } }" class="text-xs text-primary hover:underline">查看条目</RouterLink>
              <span v-if="x.error" class="w-full text-xs text-bad">{{ x.error }}</span>
            </li>
          </ul>
        </template>

        <!-- 后台任务 -->
        <template v-else-if="current.extra?.items?.length">
          <h3 class="mt-5 mb-2 text-[13px] font-semibold">条目（{{ current.extra.items.length }}）</h3>
          <ul class="m-0 list-none p-0">
            <li v-for="x in current.extra.items" :key="x.id" class="border-b border-dashed border-line py-2 text-[13px] last:border-0">
              <span class="flex items-center gap-2"><RouterLink :to="{ path: '/content', query: { id: x.id } }" class="min-w-0 flex-1 truncate font-medium hover:text-primary">{{ x.name }}</RouterLink><span class="tag" :class="STAGE[x.status] || 'tag-gray'">{{ x.stage_label || x.status }}</span><span class="text-xs text-mute tabular-nums">{{ x.duration_s != null ? dur(x.duration_s) : '' }}</span></span>
              <span v-if="x.error" class="mt-0.5 block text-xs break-words text-bad">{{ x.error }}</span>
            </li>
          </ul>
        </template>

        <template v-if="current.logs?.length">
          <h3 class="mt-5 mb-2 text-[13px] font-semibold">日志（{{ current.logs.length }}）</h3>
          <ul class="m-0 list-none p-0">
            <li v-for="(l, i) in current.logs" :key="i" class="flex gap-2 border-b border-dashed border-line py-1.5 text-xs last:border-0">
              <time class="shrink-0 text-mute tabular-nums">{{ formatTime(l.at) }}</time>
              <span class="min-w-0 break-words" :class="LEVEL[l.level]">{{ l.message }}</span>
            </li>
          </ul>
        </template>
      </template>
      <template v-if="current && (current.can_retry || current.can_abort)" #footer>
        <div class="flex items-center gap-2">
          <button v-if="current.can_abort" class="btn btn-danger" :disabled="busy" @click="abort(current)">终止</button>
          <button v-if="current.can_retry && current.id.startsWith('task:') && (current.progress?.failed || 0) > 0" class="btn ml-auto" :disabled="busy" @click="retryFailed(current)">只重试失败项</button>
          <button v-if="current.can_retry" class="btn btn-primary" :class="{ 'ml-auto': !(current.id.startsWith('task:') && (current.progress?.failed || 0) > 0) }" :disabled="busy" @click="retry(current)">重试</button>
        </div>
      </template>
    </ADrawer>
  </div>
</template>
