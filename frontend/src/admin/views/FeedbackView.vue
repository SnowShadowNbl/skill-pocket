<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { api, authHeaders, formatTime, isCancelled, timeAgo } from '../../api'
import AiTag from '../../components/AiTag.vue'
import Icon from '../../components/Icon.vue'
import { authState } from '../../composables/auth'
import { toast } from '../../composables/toast'
import ABulkBar from '../components/ABulkBar.vue'
import ADrawer from '../components/ADrawer.vue'
import AFilterBar from '../components/AFilterBar.vue'
import ALogItem from '../components/ALogItem.vue'
import ASelect from '../components/ASelect.vue'
import ATable from '../components/ATable.vue'
import { runBulk } from '../composables/bulk'
import { askChoice } from '../composables/choice'
import { onActionError } from '../composables/handled'
import { askReason } from '../composables/reason'
import { useDetailRoute } from '../composables/useDetailRoute'
import { useQueryFilters } from '../composables/useQueryFilters'
import { useSelection } from '../composables/useSelection'

// 用户反馈工单：状态流转（新提交 → 处理中 → 已解决 → 已关闭）、负责人、内部备注、关联记录、回复模板、处理记录。
// P0 / P1 未解决的置顶；超时（P0 4 小时 / P1 24 小时没有首次回复）标红
const emit = defineEmits(['changed'])
const { filters, params, activeCount, reset } = useQueryFilters({ q: '', status: '', priority: '', category: '', assignee: '', sort: '', overdue: false, user_id: '', created: { from: '', to: '' } })
const detail = useDetailRoute('id')
const data = ref(null)
const page = ref(1)
const current = ref(null)
const related = ref(null)
const log = ref(null)
const tab = ref('main')
const staff = ref([])
const busy = ref(false)
const showDiag = ref(false)
const reply = ref({ text: '', files: [] })
const me = computed(() => authState.user)

const PRI = {
  P0: ['tag-bad !bg-bad !text-white', '全站不可用、数据丢失或泄露、安全问题', '立即处理'],
  P1: ['tag-bad', '核心功能不可用且无替代办法', '24 小时内'],
  P2: ['tag-warn', '功能异常但有绕过办法', '本周内'],
  P3: ['tag-blue', '界面 / 体验问题', '排入计划'],
  P4: ['tag-gray', '轻微问题或建议', '有空再做'],
}
const STATUS = { new: 'tag-blue', processing: 'tag-warn', resolved: 'tag-ok', closed: 'tag-gray', wontfix: 'tag-gray' }
const STATUS_LABEL = { new: '新提交', processing: '处理中', resolved: '已解决', closed: '已关闭', wontfix: '不处理' }
// 允许的流转（和服务端一致）；resolved / closed / wontfix 可以重新打开到处理中
const NEXT = { new: ['processing', 'resolved', 'wontfix', 'closed'], processing: ['resolved', 'wontfix', 'closed', 'new'], resolved: ['closed'], wontfix: ['closed'], closed: [] }
const REOPEN = ['resolved', 'closed', 'wontfix']
const catOptions = [{ value: '', label: '全部类别' }, { value: 'bug', label: 'Bug' }, { value: 'feature', label: '功能建议' }, { value: 'ux', label: '体验问题' }, { value: 'content', label: '内容问题' }, { value: 'account', label: '账号问题' }, { value: 'other', label: '其他' }]
const priOptions = [{ value: '', label: '全部优先级' }, ...Object.keys(PRI).map((k) => ({ value: k, label: `${k} · ${PRI[k][2]}` })), { value: 'none', label: '未定优先级' }]
const setPriOptions = [{ value: '', label: '无优先级' }, ...Object.keys(PRI).map((k) => ({ value: k, label: `${k} · ${PRI[k][1]}` }))]
const sortOptions = [{ value: '', label: '紧急优先' }, { value: 'newest', label: '最新提交' }, { value: 'oldest', label: '最早提交' }, { value: 'updated', label: '最近更新' }]
const fields = [
  { key: 'q', type: 'search', label: '搜索反馈', placeholder: '搜索内容、用户或 #编号' },
  { key: 'category', type: 'select', label: '类别', options: catOptions },
  { key: 'priority', type: 'select', label: '优先级', options: priOptions },
  { key: 'sort', type: 'select', label: '排序', options: sortOptions },
  { key: 'created', type: 'daterange', label: '提交日期' },
]
const columns = [
  { key: 'title', label: '反馈', mobile: 'title' },
  { key: 'status', label: '状态', mobile: 'meta' },
  { key: 'assignee', label: '负责人', hideBelow: 'md', mobile: 'meta' },
  { key: 'who', label: '提交人', hideBelow: 'lg', mobile: 'sub' },
  { key: 'age', label: '时间', align: 'right', mobile: 'meta' },
]
const sel = useSelection({ rows: computed(() => data.value?.items || []), total: computed(() => data.value?.total || 0), params })
const counts = computed(() => data.value?.counts)
const TABS = [['', '全部'], ['new', '新提交'], ['processing', '处理中'], ['resolved', '已解决'], ['closed', '已关闭'], ['wontfix', '不处理']]
const urgent = (fb) => ['P0', 'P1'].includes(fb.priority) && ['new', 'processing'].includes(fb.status)
const dur = (s) => (s == null ? '未知' : s < 3600 ? `${Math.max(1, Math.round(s / 60))} 分钟` : s < 86400 ? `${(s / 3600).toFixed(1)} 小时` : `${(s / 86400).toFixed(1)} 天`)
const who = (fb) => (fb.user ? fb.user.label || fb.user.nickname : fb.contact_email || '访客')

async function load(more = false) {
  page.value = more ? page.value + 1 : 1
  const p = new URLSearchParams(params.value)
  p.set('page', page.value)
  p.set('page_size', 30)
  try {
    const d = await api(`/api/admin/feedback?${p}`)
    data.value = more ? { ...d, items: [...data.value.items, ...d.items] } : d
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  }
}
watch(() => params.value.toString(), () => load(), { immediate: true })

// ---------------------------------------------------------------- 统计
const stats = ref(null)
const days = ref(30)
const showStats = ref(false)
async function loadStats() {
  try {
    stats.value = await api(`/api/admin/feedback/stats?days=${days.value}`)
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  }
}
watch([showStats, days], () => showStats.value && loadStats())

// ---------------------------------------------------------------- 详情
const patchCache = ref({ priority: '', category: '' })
watch(detail.id, async (id) => {
  current.value = null
  related.value = null
  log.value = null
  tab.value = 'main'
  showDiag.value = false
  reply.value = { text: '', files: [] }
  if (!id) return
  try {
    current.value = await api(`/api/admin/feedback/${id}`)
    patchCache.value = { priority: current.value.priority || '', category: current.value.category }
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
    detail.close()
  }
}, { immediate: true })
watch(tab, async (t) => {
  const id = current.value?.id
  if (!id) return
  try {
    if (t === 'notes' && !related.value) related.value = await api(`/api/admin/feedback/${id}/related`)
    if (t === 'log') log.value = await api(`/api/admin/activity?target_type=feedback&target_id=${id}&page_size=50`)
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  }
})

function apply(row) {
  // 接口返回的列表项合并回当前详情和列表
  current.value = { ...current.value, ...row }
  patchCache.value = { priority: row.priority || '', category: row.category }
  if (data.value) data.value.items = data.value.items.map((x) => (x.id === row.id ? { ...x, ...row } : x))
  if (log.value) tab.value === 'log' && watchLog()
  emit('changed')
}
async function watchLog() {
  log.value = await api(`/api/admin/activity?target_type=feedback&target_id=${current.value.id}&page_size=50`).catch(() => log.value)
}
async function reloadAll() {
  await load()
  if (detail.id.value) {
    try {
      apply(await api(`/api/admin/feedback/${detail.id.value}`))
    } catch {}
  }
}

// ---------------------------------------------------------------- 状态、负责人、优先级
async function patch(body, reason = '') {
  busy.value = true
  try {
    const r = await api(`/api/admin/feedback/${current.value.id}`, { method: 'PATCH', body: { ...body, reason, expected_status: current.value.status } })
    apply(r)
    if (r.notified) toast('已通知用户', 'success')
    return r
  } catch (e) {
    await onActionError(e, reloadAll)
    return null
  } finally {
    busy.value = false
  }
}
async function setStatus(s) {
  const c = current.value
  let reason = ''
  if (REOPEN.includes(c.status) && s === 'processing') {
    reason = await askReason({ title: `重新打开反馈 #${c.id}`, impact: '状态回到「处理中」，已解决 / 关闭时间会清空', templates: ['用户反馈问题仍然存在', '修复不完整，需要继续处理'], okText: '重新打开' })
    if (reason === null) return
  } else if (['wontfix', 'closed'].includes(s)) {
    reason = await askReason({
      title: s === 'wontfix' ? `不处理反馈 #${c.id}` : `关闭反馈 #${c.id}`,
      impact: c.user ? '会给提交人发一条站内通知' : '访客反馈，不会通知到对方',
      templates: s === 'wontfix' ? ['属于预期行为', '暂不在计划内', '无法复现，信息不足'] : ['问题已处理完毕', '重复反馈，已合并'],
      okText: s === 'wontfix' ? '不处理' : '关闭',
    })
    if (reason === null) return
  }
  await patch({ status: s }, reason)
}
const savePatch = () => patch({ priority: patchCache.value.priority, category: patchCache.value.category })
const patchDirty = computed(() => current.value && (patchCache.value.priority !== (current.value.priority || '') || patchCache.value.category !== current.value.category))

async function loadStaff() {
  if (staff.value.length) return staff.value
  try {
    const d = await api('/api/admin/feedback/assignees')
    staff.value = (d.items || []).map((s) => ({ value: s.id, label: `${s.label}（${s.role_label}）` }))
  } catch {}
  return staff.value
}
async function assign(id) {
  busy.value = true
  try {
    apply(await api(`/api/admin/feedback/${current.value.id}/assign`, { method: 'POST', body: { assignee_id: id, expected_status: current.value.status } }))
    toast(id == null ? '已取消分配' : id === me.value?.id ? '已认领' : '已分配', 'success')
  } catch (e) {
    await onActionError(e, reloadAll)
  } finally {
    busy.value = false
  }
}
async function pickAssignee() {
  const opts = await loadStaff()
  const v = await askChoice({ title: '分配负责人', options: opts, placeholder: '选择管理员', okText: '分配' })
  if (v != null) assign(v)
}

// ---------------------------------------------------------------- 回复（含模板）
const replyInput = ref(null)
const sending = ref('')
const templates = ref([])
async function loadTemplates() {
  try {
    templates.value = (await api('/api/admin/reply-templates?scope=feedback_reply')).items
  } catch {}
}
function useTemplate(t) {
  const name = current.value?.user?.nickname || '你'
  reply.value.text = t.text.replaceAll('{nickname}', name).replaceAll('{id}', current.value.id)
}
function addFiles(e) {
  const picked = [...(e.target.files || [])].filter((x) => x.type.startsWith('image/'))
  e.target.value = ''
  const room = 3 - reply.value.files.length
  reply.value.files = [...reply.value.files, ...picked.slice(0, room).map((file) => ({ file, url: URL.createObjectURL(file) }))]
  if (picked.length > room) toast('最多附 3 张图片', 'error')
}
function dropFile(i) {
  URL.revokeObjectURL(reply.value.files[i].url)
  reply.value.files.splice(i, 1)
}
async function sendReply(status = '') {
  const c = current.value
  sending.value = status || 'reply'
  const fd = new FormData()
  fd.append('text', reply.value.text.trim())
  fd.append('expected_status', c.status)
  if (status) fd.append('status', status)
  reply.value.files.forEach((x) => fd.append('images', x.file))
  try {
    const res = await fetch(`/api/admin/feedback/${c.id}/replies`, { method: 'POST', body: fd, headers: authHeaders() })
    const r = await res.json().catch(() => ({}))
    if (!res.ok) {
      const err = new Error(r.detail?.message || (typeof r.detail === 'string' ? r.detail : `发送失败（${res.status}）`))
      err.code = r.detail?.code
      throw err
    }
    reply.value.files.forEach((x) => URL.revokeObjectURL(x.url))
    reply.value = { text: '', files: [] }
    apply(r)
    toast(r.notified ? '已回复，用户会收到站内通知' : c.user ? '已回复' : '已保存（访客反馈不会通知到对方）', 'success')
  } catch (e) {
    await onActionError(e, reloadAll)
  } finally {
    sending.value = ''
  }
}

// ---------------------------------------------------------------- 内部备注
const noteText = ref('')
async function addNote() {
  const text = noteText.value.trim()
  if (!text) return
  try {
    const r = await api(`/api/admin/feedback/${current.value.id}/notes`, { method: 'POST', body: { text } })
    current.value = { ...current.value, notes: r.notes }
    noteText.value = ''
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  }
}
async function delNote(n) {
  try {
    const r = await api(`/api/admin/feedback/${current.value.id}/notes/${n.id}`, { method: 'DELETE' })
    current.value = { ...current.value, notes: r.notes }
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  }
}

// ---------------------------------------------------------------- 批量
const reasonOf = (title, impact, templates) => ({ title, impact, templates, okText: '确定' })
const bulkActions = [
  { key: 'assign', label: '分配', icon: 'user',
    pick: async () => {
      const v = await askChoice({ title: '批量分配负责人', options: await loadStaff(), placeholder: '选择管理员', okText: '分配' })
      return v == null ? null : { assignee_id: v }
    },
    run: (scope, reason, params) => runBulk('/api/admin/feedback/bulk', { action: 'assign', scope, reason, params }) },
  { key: 'status', label: '改状态', icon: 'refresh',
    pick: async () => {
      const v = await askChoice({ title: '批量改状态', options: ['processing', 'resolved', 'wontfix', 'closed'].map((k) => ({ value: k, label: STATUS_LABEL[k] })), placeholder: '选择状态', okText: '下一步' })
      return v == null ? null : { status: v }
    },
    reason: reasonOf('批量改状态', (n) => `将修改 ${n} 个反馈的状态，已解决 / 关闭 / 不处理会通知提交人`, ['批量处理', '问题已处理完毕']),
    run: (scope, reason, params) => runBulk('/api/admin/feedback/bulk', { action: 'status', scope, reason, params }) },
  { key: 'priority', label: '改优先级', icon: 'alert', more: true,
    pick: async () => {
      const v = await askChoice({ title: '批量改优先级', options: Object.keys(PRI).map((k) => ({ value: k, label: `${k} · ${PRI[k][1]}` })), placeholder: '选择优先级', okText: '下一步' })
      return v == null ? null : { priority: v }
    },
    reason: reasonOf('批量改优先级', (n) => `将修改 ${n} 个反馈的优先级`, ['重新评估优先级']),
    run: (scope, reason, params) => runBulk('/api/admin/feedback/bulk', { action: 'priority', scope, reason, params }) },
  { key: 'close', label: '关闭', icon: 'lock', more: true, danger: true,
    reason: reasonOf('批量关闭反馈', (n) => `将关闭 ${n} 个反馈，提交人会收到站内通知`, ['问题已处理完毕', '重复反馈，已合并']),
    run: (scope, reason) => runBulk('/api/admin/feedback/bulk', { action: 'close', scope, reason }) },
]

// 快捷筛选：我负责的 / 未分配 / 超时
const chip = (key, val) => (filters[key] === val ? (filters[key] = key === 'overdue' ? false : '') : (filters[key] = val))

// AI 分析中的反馈每 8 秒刷新一次第一页
const timer = setInterval(() => {
  if (!document.hidden && page.value === 1 && data.value?.items.some((x) => x.ai_status === 'pending')) load()
}, 8000)
onBeforeUnmount(() => clearInterval(timer))
onMounted(() => {
  loadTemplates()
})
</script>

<template>
  <div>
    <div class="flex flex-wrap items-center gap-3">
      <h1 class="m-0 text-xl font-semibold">用户反馈</h1>
      <button class="btn ml-auto" :aria-expanded="showStats" @click="showStats = !showStats"><Icon name="trend" :size="14" />统计</button>
    </div>

    <section v-if="showStats" class="card mt-4">
      <div class="card-hd"><h2>工单统计</h2><div class="seg ml-auto"><button v-for="d in [7, 30, 90]" :key="d" :class="{ on: days === d }" @click="days = d">{{ d }} 天</button></div></div>
      <div v-if="!stats" class="card-bd"><div class="skeleton h-20" /></div>
      <div v-else class="card-bd">
        <ul class="m-0 grid list-none grid-cols-2 gap-2.5 p-0 sm:grid-cols-4">
          <li class="rounded-lg bg-subtle px-3 py-2"><p class="m-0 text-xs text-mute">工单数</p><b class="text-lg tabular-nums">{{ stats.total }}</b></li>
          <li class="rounded-lg bg-subtle px-3 py-2"><p class="m-0 text-xs text-mute">平均首次响应</p><b class="text-lg">{{ dur(stats.avg_first_response_s) }}</b></li>
          <li class="rounded-lg bg-subtle px-3 py-2"><p class="m-0 text-xs text-mute">平均处理时长</p><b class="text-lg">{{ dur(stats.avg_resolve_s) }}</b></li>
          <li class="rounded-lg px-3 py-2" :class="stats.overdue_count ? 'bg-bad-soft' : 'bg-subtle'"><p class="m-0 text-xs" :class="stats.overdue_count ? 'text-bad' : 'text-mute'">超时未响应</p><b class="text-lg tabular-nums" :class="{ 'text-bad': stats.overdue_count }">{{ stats.overdue_count }}</b></li>
        </ul>
        <p v-if="stats.by_category.length" class="m-0 mt-3 flex flex-wrap gap-1.5"><span v-for="c in stats.by_category" :key="c.key" class="tag tag-gray">{{ c.label }} {{ c.count }}</span></p>
        <table v-if="stats.by_assignee.length" class="tbl mt-3">
          <thead><tr><th>负责人</th><th class="text-right">处理中</th><th class="text-right">已结束</th></tr></thead>
          <tbody><tr v-for="a in stats.by_assignee" :key="a.user.id"><td>{{ a.user.label }}</td><td class="text-right tabular-nums">{{ a.open }}</td><td class="text-right tabular-nums">{{ a.resolved }}</td></tr></tbody>
        </table>
      </div>
    </section>

    <section class="card mt-4">
      <div class="flex flex-wrap items-center gap-2 border-b border-line px-3.5 py-3">
        <div class="seg flex-wrap">
          <button v-for="t in TABS" :key="t[0]" :class="{ on: filters.status === t[0] }" @click="filters.status = t[0]">
            {{ t[1] }}<b v-if="counts && t[0] && counts[t[0]]" class="ml-1 tabular-nums" :class="filters.status === t[0] ? '' : t[0] === 'new' ? 'text-warn' : 'text-mute'">{{ counts[t[0]] }}</b>
          </button>
        </div>
        <span class="flex flex-wrap gap-1.5 sm:ml-auto">
          <button class="flex h-8 items-center gap-1 rounded-full border px-3 text-[12.5px]" :class="filters.assignee === 'me' ? 'border-primary bg-primary-soft text-primary' : 'border-line text-ink-2'" :aria-pressed="filters.assignee === 'me'" @click="chip('assignee', 'me')">我负责<b v-if="counts?.mine" class="tabular-nums">{{ counts.mine }}</b></button>
          <button class="flex h-8 items-center gap-1 rounded-full border px-3 text-[12.5px]" :class="filters.assignee === 'none' ? 'border-primary bg-primary-soft text-primary' : 'border-line text-ink-2'" :aria-pressed="filters.assignee === 'none'" @click="chip('assignee', 'none')">未分配<b v-if="counts?.unassigned" class="tabular-nums">{{ counts.unassigned }}</b></button>
          <button class="flex h-8 items-center gap-1 rounded-full border px-3 text-[12.5px]" :class="filters.overdue ? 'border-bad bg-bad-soft text-bad' : 'border-line text-ink-2'" :aria-pressed="filters.overdue" @click="chip('overdue', true)">超时<b v-if="counts?.overdue" class="tabular-nums">{{ counts.overdue }}</b></button>
        </span>
      </div>
      <AFilterBar :filters="filters" :fields="fields" :active-count="activeCount - (filters.status ? 1 : 0) - (filters.assignee ? 1 : 0) - (filters.overdue ? 1 : 0)" @reset="reset" />
      <p v-if="filters.user_id" class="m-0 flex items-center gap-2 border-b border-line bg-primary-soft px-[18px] py-2 text-[13px] text-primary">只看用户 #{{ filters.user_id }} 的反馈<button class="ml-auto underline" @click="filters.user_id = ''">看全部</button></p>
      <ATable :columns="columns" :rows="data?.items || []" :loading="!data" :selection="sel" clickable empty-text="没有符合条件的反馈" @row-click="(fb) => detail.open(fb.id)">
        <template #cell-title="{ row: fb }">
          <span class="flex items-start gap-2.5" :class="{ 'rounded-md bg-bad-soft/50': urgent(fb) }">
            <span class="tag mt-0.5 w-9 shrink-0 justify-center font-bold" :class="fb.priority ? PRI[fb.priority][0] : 'tag-gray'">{{ fb.priority || '—' }}</span>
            <span class="min-w-0">
              <span class="block max-w-[420px] truncate font-medium">{{ fb.ai_analysis?.summary || fb.content.slice(0, 60) }}</span>
              <span class="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-mute">
                <span class="tag tag-gray">{{ fb.category_label }}</span>
                <span v-if="fb.overdue" class="tag tag-bad">超时</span>
                <span v-if="fb.ai_status === 'pending'" class="tag tag-blue"><Icon name="refresh" :size="12" class="animate-spin" />AI 分析中</span>
                <span v-if="fb.admin_reply" class="tag tag-ok">已回复</span>
                <span>#{{ fb.id }}</span>
              </span>
            </span>
          </span>
        </template>
        <template #cell-status="{ row: fb }"><span class="tag" :class="STATUS[fb.status]">{{ fb.status_label }}</span></template>
        <template #cell-assignee="{ row: fb }"><span class="text-[13px]" :class="fb.assignee ? '' : 'text-mute'">{{ fb.assignee?.label || '未分配' }}</span></template>
        <template #cell-who="{ row: fb }">{{ who(fb) }}</template>
        <template #cell-age="{ row: fb }"><span class="text-xs whitespace-nowrap text-mute">{{ timeAgo(fb.created_at) }}</span></template>
      </ATable>
      <div v-if="data" class="flex items-center border-t border-line px-[18px] py-3 text-xs text-mute">
        共 {{ data.total }} 条
        <button v-if="data.items.length < data.total" class="btn btn-sm ml-auto" @click="load(true)">加载更多</button>
      </div>
    </section>
    <ABulkBar :selection="sel" :actions="bulkActions" noun="条反馈" @done="reloadAll" />

    <!-- 反馈详情与处理 -->
    <ADrawer :open="!!detail.id.value" label="反馈详情" :width="680" @close="detail.close()">
      <template #header>
        <p v-if="!current" class="m-0 text-mute">加载中…</p>
        <div v-else class="flex items-center gap-2.5">
          <span class="tag w-10 shrink-0 justify-center font-bold" :class="current.priority ? PRI[current.priority][0] : 'tag-gray'">{{ current.priority || '—' }}</span>
          <div class="min-w-0">
            <p class="m-0 font-semibold">反馈 #{{ current.id }} · {{ current.category_label }}<span class="tag ml-2" :class="STATUS[current.status]">{{ current.status_label }}</span><span v-if="current.overdue" class="tag tag-bad ml-1">超时</span></p>
            <p class="m-0 truncate text-xs text-mute">{{ who(current) }} · {{ formatTime(current.created_at) }}</p>
          </div>
        </div>
      </template>
      <div v-if="!current" class="skeleton h-72" />
      <template v-else>
        <div class="flex flex-wrap items-center gap-2 rounded-lg bg-subtle px-3 py-2 text-[13px]">
          <span class="text-mute">负责人</span><b class="font-medium">{{ current.assignee?.label || '未分配' }}</b>
          <span class="ml-auto flex gap-1.5">
            <button v-if="current.assignee?.id !== me?.id" class="btn btn-sm" :disabled="busy" @click="assign(me.id)">认领</button>
            <button class="btn btn-sm" :disabled="busy" @click="pickAssignee">分配给…</button>
            <button v-if="current.assignee" class="btn btn-sm" :disabled="busy" @click="assign(null)">取消分配</button>
          </span>
        </div>
        <div class="seg mt-3 mb-4"><button :class="{ on: tab === 'main' }" @click="tab = 'main'">处理</button><button :class="{ on: tab === 'notes' }" @click="tab = 'notes'">备注与关联<b v-if="current.notes?.length" class="ml-1 tabular-nums">{{ current.notes.length }}</b></button><button :class="{ on: tab === 'log' }" @click="tab = 'log'">处理记录</button></div>

        <template v-if="tab === 'main'">
          <p class="m-0 text-[14px] leading-relaxed break-words whitespace-pre-wrap">{{ current.content }}</p>
          <div v-if="current.images.length" class="mt-3 flex flex-wrap gap-2">
            <a v-for="src in current.images" :key="src" :href="src" target="_blank" class="h-24 w-24 overflow-hidden rounded-lg border border-line"><img :src="src" alt="反馈截图" class="h-full w-full object-cover" /></a>
          </div>
          <p class="mt-3 mb-0 text-xs text-mute">页面：<span class="break-all">{{ current.page_url || '—' }}</span><a v-if="current.item_id" :href="`/items/${current.item_id}`" target="_blank" class="ml-2 text-primary hover:underline">相关条目</a></p>
          <p class="mt-1 mb-0 text-xs text-mute">首次响应 {{ dur(current.first_response_s) }}<template v-if="current.resolve_s != null"> · 处理用时 {{ dur(current.resolve_s) }}</template></p>

          <div v-if="current.ai_status === 'done'" class="mt-4 rounded-lg border border-[#d6e4fb] bg-primary-soft/50 p-3.5 text-[13.5px] leading-relaxed">
            <p class="m-0 mb-2 flex items-center gap-2 font-semibold text-primary">分析<AiTag :model="current.ai_analysis.model" /></p>
            <p v-if="current.ai_analysis.priority" class="m-0"><b>优先级 {{ current.ai_analysis.priority }}：</b>{{ current.ai_analysis.priority_reason }}</p>
            <p v-if="current.ai_analysis.suggested_category && current.ai_analysis.suggested_category !== current.category" class="m-0 text-warn"><b>建议类别：</b>{{ catOptions.find((c) => c.value === current.ai_analysis.suggested_category)?.label }}（用户选的是 {{ current.category_label }}）</p>
            <p v-if="current.ai_analysis.cause" class="m-0"><b>可能原因：</b>{{ current.ai_analysis.cause }}</p>
            <p v-if="current.ai_analysis.modules?.length" class="m-0"><b>涉及模块：</b>{{ current.ai_analysis.modules.join('、') }}</p>
            <p v-if="current.ai_analysis.impact" class="m-0"><b>影响面：</b>{{ current.ai_analysis.impact }}</p>
            <div v-if="current.ai_analysis.steps?.length"><b>处理建议：</b><ol class="m-0 mt-1 list-decimal pl-5"><li v-for="(s, i) in current.ai_analysis.steps" :key="i">{{ s }}</li></ol></div>
          </div>
          <p v-else-if="current.ai_status === 'pending'" class="mt-4 mb-0 flex items-center gap-1.5 text-[13px] text-primary"><Icon name="refresh" :size="14" class="animate-spin" />AI 正在分析…</p>
          <p v-else-if="current.ai_status === 'failed'" class="mt-4 mb-0 text-[13px] text-bad">AI 分析失败：{{ current.ai_analysis.error }}</p>

          <div v-if="Object.keys(current.diagnostics || {}).length" class="mt-3 rounded-lg border border-line">
            <button class="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-ink-2" :aria-expanded="showDiag" @click="showDiag = !showDiag">
              诊断信息：{{ (current.diagnostics.errors || []).length }} 条报错 · {{ (current.diagnostics.failed_requests || []).length }} 个失败请求
              <Icon name="chevron-down" :size="14" class="ml-auto transition-transform" :class="{ 'rotate-180': showDiag }" />
            </button>
            <pre v-if="showDiag" class="m-0 max-h-60 overflow-auto border-t border-line bg-subtle px-3 py-2 font-mono text-[11.5px] leading-relaxed whitespace-pre-wrap text-ink-2">{{ JSON.stringify(current.diagnostics, null, 2) }}</pre>
          </div>

          <h3 class="mt-5 mb-2.5 text-[13px] font-semibold">状态</h3>
          <div class="flex flex-wrap gap-2">
            <button v-for="s in (REOPEN.includes(current.status) ? ['processing', ...NEXT[current.status]] : NEXT[current.status])" :key="s" class="btn btn-sm" :class="s === 'processing' && REOPEN.includes(current.status) ? '' : s === 'resolved' ? 'btn-primary' : ''" :disabled="busy" @click="setStatus(s)">
              {{ s === 'processing' && REOPEN.includes(current.status) ? '重新打开' : { processing: '开始处理', resolved: '标记已解决', wontfix: '不处理', closed: '关闭', new: '退回新提交' }[s] }}
            </button>
            <span v-if="!NEXT[current.status].length && !REOPEN.includes(current.status)" class="text-xs text-mute">没有可用的流转</span>
          </div>
          <div class="mt-3 grid gap-2.5 sm:grid-cols-[1fr_1fr_auto]">
            <ASelect v-model="patchCache.priority" :options="setPriOptions" label="优先级" />
            <ASelect v-model="patchCache.category" :options="catOptions.slice(1)" label="类别" />
            <button class="btn btn-primary" :disabled="busy || !patchDirty" @click="savePatch">保存</button>
          </div>

          <h3 class="mt-5 mb-2.5 text-[13px] font-semibold">回复用户<span v-if="!current.user" class="ml-1.5 font-normal text-mute">（访客反馈，回复不会通知到对方）</span></h3>
          <ol v-if="current.replies?.length" class="m-0 mb-3 list-none space-y-2 p-0">
            <li v-for="(r, i) in current.replies" :key="i" class="rounded-lg bg-primary-soft px-3 py-2.5 text-[13px] leading-relaxed">
              <p class="m-0 mb-1 text-xs text-primary">{{ r.by || '管理员' }} · {{ r.at ? formatTime(r.at) : '' }}</p>
              <p v-if="r.text" class="m-0 whitespace-pre-wrap">{{ r.text }}</p>
              <div v-if="r.images?.length" class="mt-2 flex gap-2"><a v-for="src in r.images" :key="src" :href="src" target="_blank" class="h-16 w-16 overflow-hidden rounded-md border border-line"><img :src="src" alt="回复图片" class="h-full w-full object-cover" /></a></div>
            </li>
          </ol>
          <div v-if="templates.length" class="mb-2 flex flex-wrap gap-1.5">
            <button v-for="t in templates" :key="t.id" type="button" class="h-7 rounded-full border border-line px-2.5 text-xs text-ink-2 hover:border-primary hover:text-primary" @click="useTemplate(t)">{{ t.title }}</button>
          </div>
          <textarea v-model="reply.text" rows="3" class="input h-auto resize-y py-2" placeholder="写回复，可以点上面的模板，也可以附截图" />
          <div class="mt-2 flex flex-wrap items-center gap-2">
            <div v-for="(x, i) in reply.files" :key="x.url" class="relative h-14 w-14 overflow-hidden rounded-md border border-line">
              <img :src="x.url" alt="" class="h-full w-full object-cover" />
              <button class="absolute top-0.5 right-0.5 grid h-5 w-5 place-items-center rounded-full bg-ink/60 text-white" aria-label="移除图片" @click="dropFile(i)"><Icon name="x" :size="11" /></button>
            </div>
            <button v-if="reply.files.length < 3" class="btn btn-sm" @click="replyInput.click()"><Icon name="image" :size="14" />附图片</button>
            <input ref="replyInput" type="file" accept="image/*" multiple class="hidden" @change="addFiles" />
            <span class="flex-1" />
            <button v-if="current.status !== 'resolved' && current.status !== 'closed'" class="btn btn-sm" :disabled="!!sending" @click="sendReply('resolved')"><Icon :name="sending === 'resolved' ? 'refresh' : 'check'" :size="14" :class="{ 'animate-spin': sending === 'resolved' }" />{{ reply.text.trim() || reply.files.length ? '回复并标记已解决' : '标记已解决' }}</button>
            <button class="btn btn-primary btn-sm" :disabled="!!sending || (!reply.text.trim() && !reply.files.length)" @click="sendReply()"><Icon :name="sending === 'reply' ? 'refresh' : 'send'" :size="14" :class="{ 'animate-spin': sending === 'reply' }" />发送回复</button>
          </div>
        </template>

        <template v-else-if="tab === 'notes'">
          <h3 class="m-0 mb-2 text-[13px] font-semibold">内部备注<span class="ml-1.5 text-xs font-normal text-mute">只有管理员看得到</span></h3>
          <p v-if="!current.notes?.length" class="m-0 text-[13px] text-mute">还没有备注</p>
          <ul class="m-0 list-none p-0">
            <li v-for="n in current.notes" :key="n.id" class="border-b border-dashed border-line py-2 text-[13px] last:border-0">
              <p class="m-0 break-words whitespace-pre-wrap">{{ n.text }}</p>
              <p class="m-0 mt-1 flex items-center text-xs text-mute">{{ n.by?.label }} · {{ formatTime(n.at) }}<button v-if="n.can_delete" class="ml-auto text-mute hover:text-bad" @click="delNote(n)">删除</button></p>
            </li>
          </ul>
          <div class="mt-2 flex gap-2"><input v-model="noteText" class="input" maxlength="1000" placeholder="写一条备注" aria-label="内部备注" @keydown.enter="addNote" /><button class="btn btn-primary shrink-0" :disabled="!noteText.trim()" @click="addNote">添加</button></div>

          <h3 class="mt-5 mb-2 text-[13px] font-semibold">关联记录</h3>
          <div v-if="!related" class="skeleton h-24" />
          <template v-else>
            <dl class="m-0 grid grid-cols-[76px_1fr] gap-x-3 gap-y-2 text-[13px]">
              <dt class="text-mute">用户</dt>
              <dd class="m-0"><template v-if="related.user"><RouterLink :to="{ path: '/users', query: { id: related.user.id } }" class="text-primary hover:underline">{{ related.user.label }}</RouterLink><span class="ml-2 text-xs text-mute">{{ related.user.signup_channel_label }} · {{ related.user.last_client_label }}<template v-if="related.user.last_client_version"> {{ related.user.last_client_version }}</template></span></template><template v-else>访客</template></dd>
              <dt class="text-mute">相关条目</dt>
              <dd class="m-0"><RouterLink v-if="related.item" :to="{ path: '/content', query: { id: related.item.id } }" class="text-primary hover:underline">{{ related.item.name }}</RouterLink><template v-else>—</template></dd>
              <dt class="text-mute">报错记录</dt><dd class="m-0 text-mute">未知</dd>
            </dl>
            <h4 class="mt-4 mb-1.5 text-xs font-semibold text-ink-2">TA 的其他反馈</h4>
            <p v-if="!related.user_feedbacks.length" class="m-0 text-[13px] text-mute">没有</p>
            <ul class="m-0 list-none p-0"><li v-for="x in related.user_feedbacks" :key="x.id" class="flex items-center gap-2 border-b border-dashed border-line py-1.5 text-[13px] last:border-0"><RouterLink :to="{ path: '/feedback', query: { id: x.id } }" class="min-w-0 flex-1 truncate hover:text-primary">#{{ x.id }} {{ x.summary }}</RouterLink><span class="tag" :class="STATUS[x.status]">{{ x.status_label }}</span></li></ul>
            <template v-if="related.client_errors">
              <h4 class="mt-4 mb-1.5 text-xs font-semibold text-ink-2">TA 最近的报错</h4>
              <p v-if="!related.client_errors.length" class="m-0 text-[13px] text-mute">没有</p>
              <ul class="m-0 list-none p-0"><li v-for="x in related.client_errors" :key="x.id" class="border-b border-dashed border-line py-1.5 text-[13px] last:border-0"><span class="tag tag-gray mr-1.5">{{ x.kind_label }}</span><span class="break-words">{{ x.message }}</span><span class="block text-xs break-all text-mute">{{ x.client_label }}<template v-if="x.version"> {{ x.version }}</template> · {{ x.page || '未知页面' }} · {{ x.count }} 次 · {{ formatTime(x.last_at) }}</span></li></ul>
            </template>
            <h4 class="mt-4 mb-1.5 text-xs font-semibold text-ink-2">TA 的收录任务</h4>
            <p v-if="!related.user_tasks.length" class="m-0 text-[13px] text-mute">没有</p>
            <ul class="m-0 list-none p-0"><li v-for="x in related.user_tasks" :key="x.id" class="flex items-center gap-2 border-b border-dashed border-line py-1.5 text-[13px] last:border-0"><RouterLink :to="{ path: '/ingest-tasks', query: { id: x.id } }" class="min-w-0 flex-1 truncate hover:text-primary">{{ x.title }}</RouterLink><span class="tag tag-gray">{{ x.status_label }}</span></li></ul>
            <h4 class="mt-4 mb-1.5 text-xs font-semibold text-ink-2">相似反馈</h4>
            <p v-if="!related.similar.length" class="m-0 text-[13px] text-mute">没有</p>
            <ul class="m-0 list-none p-0"><li v-for="x in related.similar" :key="x.id" class="flex items-center gap-2 border-b border-dashed border-line py-1.5 text-[13px] last:border-0"><RouterLink :to="{ path: '/feedback', query: { id: x.id } }" class="min-w-0 flex-1 truncate hover:text-primary">#{{ x.id }} {{ x.summary }}</RouterLink><span class="tag" :class="STATUS[x.status]">{{ x.status_label }}</span></li></ul>
          </template>
        </template>

        <template v-else>
          <div v-if="!log" class="skeleton h-40" />
          <p v-else-if="!log.items.length" class="empty">没有处理记录</p>
          <ul v-else class="m-0 list-none p-0">
            <li v-for="r in log.items" :key="r.id" class="border-b border-dashed border-line py-2.5 text-[13px] last:border-0">
              <span class="mb-1 flex flex-wrap items-center gap-1.5"><span class="tag tag-blue">{{ r.action_label }}</span><span class="text-xs text-ink-2">{{ r.user?.label || '系统' }}</span><span class="text-xs text-mute">{{ formatTime(r.created_at) }}</span></span>
              <ALogItem :row="r" compact />
            </li>
          </ul>
        </template>
      </template>
    </ADrawer>
  </div>
</template>
