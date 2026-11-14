<script setup>
import { computed, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { api, formatTime, isCancelled } from '../../api'
import Icon from '../../components/Icon.vue'
import UserAvatar from '../../components/UserAvatar.vue'
import { toast } from '../../composables/toast'
import AFilterBar from '../components/AFilterBar.vue'
import { onActionError } from '../composables/handled'
import { askReason } from '../composables/reason'
import { reasonTemplates } from '../composables/useReasonTemplates'
import { useQueryFilters } from '../composables/useQueryFilters'
import { REASONS } from '../reasons'

// 评论审核：待审核 / 已公开 / 已驳回 / 已删除。AI 拿不准的进待审核；驳回、删除、恢复都要填原因并留处置历史，
// 带评分的评论被处置后条目评分会自动重算，这里显示重算前后的变化。
const emit = defineEmits(['changed'])
const { filters, params, activeCount, reset } = useQueryFilters({ status: 'pending', q: '', id: '', user_id: '', item_id: '' })
const data = ref(null)
const page = ref(1)
const busy = ref(0)
const ratingChange = ref({}) // 评论编号 → { before, after }（刚处置过的）
const history = ref({}) // 评论编号 → 处置历史（展开后才加载）
const openHistory = ref(new Set())

const TABS = [['pending', '待审核'], ['visible', '已公开'], ['rejected', '已驳回'], ['deleted', '已删除'], ['all', '全部']]
const STATUS = { pending: ['待审核', 'tag-warn'], visible: ['已公开', 'tag-ok'], rejected: ['已驳回', 'tag-bad'], deleted: ['已删除', 'tag-gray'] }
const fields = [{ key: 'q', type: 'search', label: '搜索评论内容' }]
const status = computed(() => filters.status || 'pending')
const setStatus = (s) => { filters.status = s }
const emptyText = computed(() => (filters.id ? '没有这条评论' : status.value === 'pending' ? '没有待审核的评论' : '没有评论'))

async function load(more = false) {
  page.value = more ? page.value + 1 : 1
  const p = new URLSearchParams(params.value)
  if (!p.has('status')) p.set('status', 'pending')
  p.set('page', page.value)
  p.set('page_size', 30)
  try {
    const d = await api(`/api/admin/comments?${p}`)
    data.value = more ? { ...d, items: [...data.value.items, ...d.items] } : d
    if (filters.id && d.items[0]) toggleHistory(d.items[0], true)
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  }
}
watch(() => params.value.toString(), () => load(), { immediate: true })

const ratingText = (r) => (r ? `${r.avg ?? '—'}（${r.count} 人）` : '—')
const changed = (r) => r && (r.before.avg !== r.after.avg || r.before.count !== r.after.count)

function replace(c, ratings) {
  data.value.items = data.value.items.map((x) => (x.id === c.id ? c : x))
  if (changed(ratings)) ratingChange.value = { ...ratingChange.value, [c.id]: ratings }
  if (history.value[c.id]) loadHistory(c.id)
}

// 处置：通用流程。needReason 的先弹原因弹窗（带模板）
async function act(c, action, opts = {}) {
  let reason = ''
  if (opts.reason) {
    reason = await askReason({
      title: opts.reason.title,
      impact: opts.reason.impact,
      templates: await reasonTemplates(opts.reason.scope, opts.reason.fallback),
      danger: opts.reason.danger,
      okText: opts.reason.okText,
    })
    if (reason === null) return
  }
  busy.value = c.id
  try {
    const r = await api(`/api/admin/comments/${c.id}/${action}`, { method: 'POST', body: { reason, expected_status: c.status } })
    toast(opts.done, 'success')
    replace(r.comment, r.item_rating)
    if (changed(r.item_rating)) toast(`条目评分 ${ratingText(r.item_rating.before)} → ${ratingText(r.item_rating.after)}`, 'info')
    emit('changed')
    if (status.value !== 'all') load()
  } catch (e) {
    await onActionError(e, load)
  } finally {
    busy.value = 0
  }
}
const approve = (c) => act(c, 'approve', { done: '已通过，评论已公开' })
const reject = (c) => act(c, 'reject', {
  done: '已驳回',
  reason: { title: '驳回这条评论', impact: '评论将被隐藏，并通知评论者', scope: 'comment_reject', fallback: REASONS.commentReject, danger: true, okText: '驳回' },
})
const remove = (c) => act(c, 'delete', {
  done: '已删除',
  reason: { title: '删除这条评论', impact: c.rating ? '评论会被隐藏，条目评分会重新计算' : '评论会被隐藏', scope: 'comment_delete', fallback: REASONS.commentDelete, danger: true, okText: '删除' },
})
const restore = (c) => act(c, 'restore', {
  done: '已恢复，评论已公开',
  reason: { title: '恢复这条评论', impact: '评论将重新公开', scope: 'comment_restore', fallback: ['误判，内容没有问题', '申诉通过'], okText: '恢复' },
})

async function loadHistory(id) {
  try {
    history.value = { ...history.value, [id]: await api(`/api/admin/comments/${id}/history`) }
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  }
}
function toggleHistory(c, forceOpen = false) {
  const s = new Set(openHistory.value)
  if (s.has(c.id) && !forceOpen) s.delete(c.id)
  else {
    s.add(c.id)
    if (!history.value[c.id]) loadHistory(c.id)
  }
  openHistory.value = s
}
</script>

<template>
  <div>
    <h1 class="m-0 mb-5 text-xl font-semibold">评论审核</h1>

    <section class="card">
      <div class="flex flex-wrap items-center gap-2 border-b border-line px-3.5 py-3">
        <div class="seg">
          <button v-for="t in TABS" :key="t[0]" :class="{ on: status === t[0] }" @click="setStatus(t[0])">
            {{ t[1] }}<b v-if="data && t[0] !== 'all' && data.counts[t[0]]" class="ml-1 tabular-nums" :class="status === t[0] ? '' : t[0] === 'pending' ? 'text-warn' : 'text-mute'">{{ data.counts[t[0]] }}</b>
          </button>
        </div>
      </div>
      <AFilterBar :filters="filters" :fields="fields" :active-count="Number(!!filters.q)" @reset="reset" />
      <p v-if="filters.id || filters.user_id || filters.item_id" class="m-0 flex items-center gap-2 border-b border-line bg-primary-soft px-[18px] py-2 text-[13px] text-primary">
        <Icon name="message" :size="14" />{{ filters.id ? `只看评论 #${filters.id}` : filters.user_id ? `只看用户 #${filters.user_id} 的评论` : `只看条目 #${filters.item_id} 的评论` }}
        <button class="ml-auto underline" @click="filters.id = ''; filters.user_id = ''; filters.item_id = ''">看全部</button>
      </p>

      <div v-if="!data" class="p-3.5"><div class="skeleton h-40" /></div>
      <p v-else-if="!data.items.length" class="empty">{{ emptyText }}</p>
      <ul v-else class="m-0 list-none divide-y divide-line p-0">
        <li v-for="c in data.items" :key="c.id" class="px-4 py-3.5">
          <div class="flex gap-3">
            <UserAvatar :user="c.author" :size="32" class="shrink-0" />
            <div class="min-w-0 flex-1">
              <div class="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-mute">
                <RouterLink :to="{ path: '/users', query: { id: c.author.id } }" class="text-[13px] font-semibold text-ink hover:text-primary">{{ c.user_label || c.author.nickname }}</RouterLink>
                <span>评论了</span>
                <RouterLink :to="{ path: '/content', query: { id: c.item_id } }" class="font-medium text-primary">{{ c.item_name }}</RouterLink>
                <b v-if="c.rating != null" class="text-warn">★{{ c.rating }}</b>
                <span class="tag" :class="STATUS[c.status]?.[1]">{{ c.status_label || STATUS[c.status]?.[0] }}</span>
                <time class="sm:ml-auto">{{ formatTime(c.created_at) }}</time>
              </div>
              <p class="mt-1 mb-0 text-[14px] leading-relaxed break-words whitespace-pre-wrap">{{ c.content }}</p>
              <p v-if="c.review_reason" class="mt-1 mb-0 flex items-start gap-1 text-[12px] text-warn"><Icon name="alert" :size="12" class="mt-0.5 shrink-0" />{{ c.review_reason }}</p>
              <p v-if="c.handled" class="mt-1 mb-0 text-xs text-ink-2">
                {{ c.handled.by?.label || '系统' }} 于 {{ formatTime(c.handled.at) }} 处理<template v-if="c.handled.reason">：{{ c.handled.reason }}</template>
              </p>
              <p v-if="ratingChange[c.id]" class="mt-1 mb-0 flex flex-wrap items-center gap-1.5 text-xs">
                <span class="tag tag-blue">条目评分</span><span class="text-mute">{{ ratingText(ratingChange[c.id].before) }}</span><span class="text-mute">→</span><b>{{ ratingText(ratingChange[c.id].after) }}</b>
              </p>
            </div>
          </div>
          <div class="mt-2.5 flex flex-wrap items-center gap-2 pl-11">
            <button class="text-xs text-mute hover:text-primary" @click="toggleHistory(c)">{{ openHistory.has(c.id) ? '收起处置历史' : '处置历史' }}</button>
            <span class="ml-auto flex flex-wrap gap-2">
              <button v-if="c.status === 'pending'" class="btn btn-sm btn-primary" :disabled="busy === c.id" @click="approve(c)">通过</button>
              <button v-if="['pending', 'visible'].includes(c.status)" class="btn btn-sm" :disabled="busy === c.id" @click="reject(c)">驳回</button>
              <button v-if="['rejected', 'deleted'].includes(c.status)" class="btn btn-sm" :disabled="busy === c.id" @click="restore(c)">恢复</button>
              <button v-if="c.status !== 'deleted'" class="btn btn-sm btn-danger" :disabled="busy === c.id" @click="remove(c)">删除</button>
            </span>
          </div>
          <ul v-if="openHistory.has(c.id)" class="m-0 mt-2.5 ml-11 list-none rounded-lg bg-subtle px-3 py-1.5 p-0">
            <li v-if="!history[c.id]" class="py-2 text-xs text-mute">加载中…</li>
            <li v-for="(h, i) in history[c.id]?.items" :key="i" class="border-b border-dashed border-line py-2 text-[13px] last:border-0">
              <span class="flex flex-wrap items-center gap-1.5"><span class="tag tag-blue">{{ h.label }}</span><span class="text-xs text-ink-2">{{ h.by?.label || 'AI / 系统' }}</span><span class="text-xs text-mute">{{ formatTime(h.at) }}</span></span>
              <span v-if="h.reason" class="mt-0.5 block text-xs text-ink-2">{{ h.action === 'create' ? (h.reason.startsWith('AI') ? '' : 'AI 判断：') : '原因：' }}{{ h.reason }}</span>
              <span v-if="h.rating && changed(h.rating)" class="mt-0.5 block text-xs text-mute">条目评分 {{ ratingText(h.rating.before) }} → {{ ratingText(h.rating.after) }}</span>
            </li>
          </ul>
        </li>
      </ul>
      <div v-if="data" class="flex items-center border-t border-line px-[18px] py-3 text-xs text-mute">
        共 {{ data.total }} 条
        <button v-if="data.items.length < data.total" class="btn btn-sm ml-auto" @click="load(true)">加载更多</button>
      </div>
    </section>
  </div>
</template>
