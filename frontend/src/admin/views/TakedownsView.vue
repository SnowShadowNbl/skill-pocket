<script setup>
import { computed, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { api, formatTime, isCancelled } from '../../api'
import { toast } from '../../composables/toast'
import ADrawer from '../components/ADrawer.vue'
import ASwitch from '../components/ASwitch.vue'
import ATable from '../components/ATable.vue'
import { onActionError } from '../composables/handled'
import { askReason } from '../composables/reason'
import { reasonTemplates } from '../composables/useReasonTemplates'
import { useDetailRoute } from '../composables/useDetailRoute'
import { REASONS } from '../reasons'

// 下架申请：原作者在条目详情页提交的申请。同意后条目隐藏（或删除），可同时把仓库加入黑名单；驳回要写理由，申请人会收到站内消息
const emit = defineEmits(['changed'])
const route = useRoute()
const router = useRouter()
const TABS = [['pending', '待处理'], ['approved', '已同意'], ['rejected', '已驳回'], ['all', '全部']]
const status = computed(() => (TABS.some((t) => t[0] === route.query.status) ? route.query.status : 'pending'))
const setStatus = (s) => router.replace({ query: { status: s === 'pending' ? undefined : s } })
const detail = useDetailRoute('id')
const data = ref(null)
const page = ref(1)
const current = ref(null)
const busy = ref(false)
const decision = ref({ action: 'hide', block: false })

const STATUS = { pending: 'tag-warn', approved: 'tag-ok', rejected: 'tag-gray' }
const RELATION = { author: 'tag-blue', maintainer: 'tag-blue', other: 'tag-gray' }
const columns = [
  { key: 'item', label: '条目', mobile: 'title' },
  { key: 'user', label: '申请人', hideBelow: 'md', mobile: 'sub' },
  { key: 'relation', label: '身份', mobile: 'meta' },
  { key: 'reason', label: '理由', hideBelow: 'lg', mobile: 'hide' },
  { key: 'status', label: '状态', mobile: 'meta' },
  { key: 'created_at', label: '申请时间', align: 'right', mobile: 'hide' },
]

async function load(more = false) {
  page.value = more ? page.value + 1 : 1
  try {
    const d = await api(`/api/admin/takedowns?status=${status.value}&page=${page.value}&page_size=30`)
    data.value = more ? { ...d, items: [...data.value.items, ...d.items] } : d
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  }
}
watch(status, () => load(), { immediate: true })

// 详情抽屉：优先用列表里的，没有就按编号取
watch(detail.id, async (id) => {
  decision.value = { action: 'hide', block: false }
  if (!id) return
  current.value = data.value?.items.find((x) => String(x.id) === id) || null
  if (current.value) return
  try {
    const d = await api(`/api/admin/takedowns?id=${id}&status=all`)
    current.value = d.items[0] || null
    if (!current.value) detail.close()
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
    detail.close()
  }
}, { immediate: true })

async function reload() {
  await load()
  if (detail.id.value) {
    const d = await api(`/api/admin/takedowns?id=${detail.id.value}&status=all`).catch(() => null)
    current.value = d?.items[0] || current.value
  }
  emit('changed')
}

async function approve(t) {
  const del = decision.value.action === 'delete'
  const reason = await askReason({
    title: `同意下架「${t.item.name}」？`,
    impact: `${del ? '条目将被删除，不能恢复' : '条目将被隐藏，之后可以恢复'}${decision.value.block ? '；同时把仓库加入黑名单' : ''}；申请人会收到站内消息`,
    templates: await reasonTemplates('takedown_approve', REASONS.takedownApprove),
    danger: true,
    okText: '同意下架',
  })
  if (reason === null) return
  busy.value = true
  try {
    await api(`/api/admin/takedowns/${t.id}/approve`, { method: 'POST', body: { reason, expected_status: t.status, action: decision.value.action, block: decision.value.block } })
    toast('已同意下架', 'success')
    await reload()
  } catch (e) {
    await onActionError(e, reload)
  } finally {
    busy.value = false
  }
}
async function reject(t) {
  const reason = await askReason({
    title: '驳回这条下架申请',
    impact: '申请人会收到站内消息，消息里带这里写的理由',
    templates: await reasonTemplates('takedown_reject', REASONS.takedownReject),
    danger: true,
    okText: '驳回',
  })
  if (reason === null) return
  busy.value = true
  try {
    await api(`/api/admin/takedowns/${t.id}/reject`, { method: 'POST', body: { reason, expected_status: t.status } })
    toast('已驳回', 'success')
    await reload()
  } catch (e) {
    await onActionError(e, reload)
  } finally {
    busy.value = false
  }
}
const itemGone = (t) => t.item.status === 'deleted'
</script>

<template>
  <div>
    <h1 class="m-0 mb-5 text-xl font-semibold">下架申请</h1>
    <section class="card">
      <div class="flex flex-wrap items-center gap-2 border-b border-line px-3.5 py-3">
        <div class="seg">
          <button v-for="t in TABS" :key="t[0]" :class="{ on: status === t[0] }" @click="setStatus(t[0])">
            {{ t[1] }}<b v-if="data && t[0] !== 'all' && data.counts[t[0]]" class="ml-1 tabular-nums" :class="status === t[0] ? '' : t[0] === 'pending' ? 'text-warn' : 'text-mute'">{{ data.counts[t[0]] }}</b>
          </button>
        </div>
      </div>
      <ATable :columns="columns" :rows="data?.items || []" :loading="!data" clickable :empty-text="status === 'pending' ? '没有待处理的申请' : '没有申请'" @row-click="(t) => detail.open(t.id)">
        <template #cell-item="{ row: t }">
          <b class="font-semibold">{{ t.item.name }}</b>
          <span v-if="t.requests_for_item > 1" class="tag tag-warn ml-1.5">{{ t.requests_for_item }} 人申请</span>
          <span class="block max-w-[320px] truncate text-xs text-mute">{{ t.repo }}</span>
        </template>
        <template #cell-user="{ row: t }">{{ t.user.label }}</template>
        <template #cell-relation="{ row: t }"><span class="tag" :class="RELATION[t.relation]">{{ t.relation_label }}</span></template>
        <template #cell-reason="{ row: t }"><span class="line-clamp-2 max-w-[360px] text-[13px] text-ink-2">{{ t.reason }}</span></template>
        <template #cell-status="{ row: t }"><span class="tag" :class="STATUS[t.status]">{{ t.status_label }}</span></template>
        <template #cell-created_at="{ row: t }"><span class="text-xs whitespace-nowrap text-mute">{{ formatTime(t.created_at) }}</span></template>
      </ATable>
      <div v-if="data" class="flex items-center border-t border-line px-[18px] py-3 text-xs text-mute">
        共 {{ data.total }} 条
        <button v-if="data.items.length < data.total" class="btn btn-sm ml-auto" @click="load(true)">加载更多</button>
      </div>
    </section>

    <ADrawer :open="!!detail.id.value" label="下架申请" @close="detail.close()">
      <template #header>
        <p v-if="!current" class="m-0 text-mute">加载中…</p>
        <div v-else>
          <p class="m-0 font-semibold">{{ current.item.name }}<span class="tag ml-2" :class="STATUS[current.status]">{{ current.status_label }}</span></p>
          <p class="m-0 truncate text-xs text-mute">{{ current.repo }}<template v-if="itemGone(current)"> · 条目已删除</template></p>
        </div>
      </template>
      <div v-if="!current" class="skeleton h-60" />
      <template v-else>
        <dl class="m-0 grid grid-cols-[76px_1fr] gap-x-3 gap-y-2 text-[13px]">
          <dt class="text-mute">申请人</dt><dd class="m-0"><RouterLink :to="{ path: '/users', query: { id: current.user.id } }" class="text-primary hover:underline">{{ current.user.label }}</RouterLink></dd>
          <dt class="text-mute">身份</dt><dd class="m-0"><span class="tag" :class="RELATION[current.relation]">{{ current.relation_label }}</span></dd>
          <dt class="text-mute">联系方式</dt><dd class="m-0 break-all">{{ current.contact || '—' }}</dd>
          <dt class="text-mute">证明链接</dt>
          <dd class="m-0 break-all"><a v-if="current.evidence_url" :href="current.evidence_url" target="_blank" rel="noopener noreferrer" class="text-primary hover:underline">{{ current.evidence_url }}</a><template v-else>—</template></dd>
          <dt class="text-mute">申请时间</dt><dd class="m-0">{{ formatTime(current.created_at) }}</dd>
          <dt v-if="current.requests_for_item > 1" class="text-mute">同一条目</dt><dd v-if="current.requests_for_item > 1" class="m-0">共 {{ current.requests_for_item }} 人申请</dd>
        </dl>
        <h3 class="mt-5 mb-2 text-[13px] font-semibold">申请理由</h3>
        <p class="m-0 text-[13.5px] leading-relaxed break-words whitespace-pre-wrap">{{ current.reason }}</p>

        <template v-if="current.handled">
          <h3 class="mt-5 mb-2 text-[13px] font-semibold">处理结果</h3>
          <p class="m-0 text-[13px]">
            {{ current.handled.by?.label || '管理员' }} 于 {{ formatTime(current.handled.at) }} {{ current.status === 'approved' ? '同意下架' : '驳回' }}<template v-if="current.status === 'approved'">（{{ current.handled.action === 'delete' ? '删除条目' : '隐藏条目' }}{{ current.handled.blocked ? '，仓库已加入黑名单' : '' }}）</template>
          </p>
          <p v-if="current.handled.reason" class="m-0 mt-1 text-xs text-ink-2">理由：{{ current.handled.reason }}</p>
        </template>

        <template v-if="current.status === 'pending' && !itemGone(current)">
          <h3 class="mt-5 mb-2 text-[13px] font-semibold">同意时</h3>
          <div class="seg mb-3"><button :class="{ on: decision.action === 'hide' }" @click="decision.action = 'hide'">隐藏条目</button><button :class="{ on: decision.action === 'delete' }" @click="decision.action = 'delete'">删除条目</button></div>
          <ASwitch v-model="decision.block" label="同时把仓库加入黑名单" />
        </template>
      </template>
      <template v-if="current && current.status === 'pending'" #footer>
        <div class="flex items-center gap-2">
          <RouterLink v-if="!itemGone(current)" :to="{ path: '/content', query: { id: current.item.id } }" class="btn">查看条目</RouterLink>
          <button class="btn ml-auto" :disabled="busy" @click="reject(current)">驳回</button>
          <button class="btn btn-danger" :disabled="busy || itemGone(current)" @click="approve(current)">同意下架</button>
        </div>
      </template>
    </ADrawer>
  </div>
</template>
