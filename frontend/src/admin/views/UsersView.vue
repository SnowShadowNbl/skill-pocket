<script setup>
import { computed, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { api, formatTime, isCancelled, timeAgo } from '../../api'
import { authState } from '../../composables/auth'
import Icon from '../../components/Icon.vue'
import UserAvatar from '../../components/UserAvatar.vue'
import { confirmDialog, promptDialog } from '../../composables/dialog'
import { toast } from '../../composables/toast'
import ADrawer from '../components/ADrawer.vue'
import AFilterBar from '../components/AFilterBar.vue'
import ABulkBar from '../components/ABulkBar.vue'
import ALogItem from '../components/ALogItem.vue'
import AExport from '../components/AExport.vue'
import TagsManager from '../components/TagsManager.vue'
import UserTagsEditor from '../components/UserTagsEditor.vue'
import { TAG_COLOR, loadTags, tagState } from '../composables/useTags'
import { askChoice } from '../composables/choice'
import ASelect from '../components/ASelect.vue'
import AViewMenu from '../components/AViewMenu.vue'
import ATable from '../components/ATable.vue'
import UserQuota from '../components/UserQuota.vue'
import { runBulk } from '../composables/bulk'
import { askReason } from '../composables/reason'
import ViewAsPanel from '../components/ViewAsPanel.vue'
import { can, hasCap } from '../composables/usePermissions'
import { callVerified } from '../composables/verify'
import { useSelection } from '../composables/useSelection'
import { useDetailRoute } from '../composables/useDetailRoute'
import { useQueryFilters } from '../composables/useQueryFilters'
import { REASONS } from '../reasons'

// 用户管理：注册用户（详情、停用、删除）、游客（未注册的访客）、IP 封禁
const route = useRoute()
const router = useRouter()
const TABS = [['users', '注册用户'], ['guests', '游客'], ['bans', 'IP 封禁']]
const tab = computed(() => (TABS.some((t) => t[0] === route.query.tab) ? route.query.tab : 'users'))
const setTab = (t) => router.replace({ query: { tab: t === 'users' ? undefined : t } })

function fail(e) {
  if (!isCancelled(e)) toast(e.message, 'error')
}

// ---------------------------------------------------------------- 注册用户
const { filters: uf, params: uParams, activeCount: uActive, reset: uReset, apply: uApply, query: uQuery } = useQueryFilters({ q: '', status: '', role: '', login: '', channel: '', client: '', client_version: '', tag: '' })
const uPage = ref(1)
const uData = ref(null)
const statusOptions = [{ value: '', label: '全部状态' }, { value: 'active', label: '正常' }, { value: 'disabled', label: '已停用' }, { value: 'deleted', label: '已注销' }, { value: 'merged', label: '已合并' }]
const roleOptions = [{ value: '', label: '全部身份' }, { value: 'user', label: '普通用户' }, { value: 'staff', label: '管理员' }]
const ROLE = { admin: ['超级管理员', 'tag-blue'], subadmin: ['子管理员', 'tag-blue'], user: ['普通用户', 'tag-gray'] }
const STATUS = { active: 'tag-ok', disabled: 'tag-bad', deleted: 'tag-gray', merged: 'tag-gray' }
const loginOptions = [{ value: '', label: '全部登录方式' }, { value: 'email_only', label: '纯邮箱' }, { value: 'wechat_only', label: '纯微信' }, { value: 'both', label: '邮箱 + 微信' }]
const channelOptions = [{ value: '', label: '全部注册渠道' }, { value: 'web-pc', label: 'PC 网页' }, { value: 'web-mobile', label: '手机网页' }, { value: 'miniprogram', label: '小程序' }, { value: 'unknown', label: '未知' }]
const clientOptions = [{ value: '', label: '全部登录端' }, { value: 'web-pc', label: 'PC 网页' }, { value: 'web-mobile', label: '手机网页' }, { value: 'miniprogram', label: '小程序' }, { value: 'unknown', label: '未知' }]
// 标签筛选：全部 / 没有标签 / 某个标签（标签管理后刷新）
const tagOptions = computed(() => [{ value: '', label: '全部标签' }, { value: 'none', label: '没有标签' }, ...tagState.value.items.map((t) => ({ value: String(t.id), label: t.name }))])
const showTags = ref(false)
loadTags().catch(() => {})
const uFields = computed(() => [
  { key: 'q', type: 'search', label: '搜索用户', placeholder: '搜索邮箱、昵称、备注名' },
  { key: 'status', type: 'select', label: '状态', options: statusOptions },
  { key: 'role', type: 'select', label: '身份', options: roleOptions },
  { key: 'login', type: 'select', label: '登录方式', options: loginOptions },
  { key: 'channel', type: 'select', label: '注册渠道', options: channelOptions },
  { key: 'client', type: 'select', label: '登录端', options: clientOptions },
  { key: 'tag', type: 'select', label: '标签', options: tagOptions.value },
])

async function loadUsers(more = false) {
  uPage.value = more ? uPage.value + 1 : 1
  try {
    const p = new URLSearchParams(uParams.value)
    p.set('page', uPage.value)
    const d = await api(`/api/admin/users?${p}`)
    uData.value = more ? { ...d, items: [...uData.value.items, ...d.items] } : d
  } catch (e) {
    fail(e)
  }
}

// 详情抽屉：用户编号在地址里（?id=），旧链接的 ?user= 自动改写
const dRoute = useDetailRoute('id', { legacy: ['user'] })
const DTABS = [['overview', '概况'], ['account', '账号与设备'], ['content', '内容与行为'], ['messages', '站内消息'], ['log', '管理记录']]
const dtab = computed(() => (DTABS.some((t) => t[0] === route.query.dtab) ? route.query.dtab : 'overview'))
const setDtab = (t) => router.replace({ query: { ...route.query, dtab: t === 'overview' ? undefined : t } })
const detail = ref(null)
const codeStat = ref(null) // 近 30 天验证码发送 / 被限频（没有邮箱时 sent 为 null）
async function openUser(id) {
  try {
    detail.value = await api(`/api/admin/users/${id}`)
    remarkDraft.value = detail.value.remark || ''
    codeStat.value = null
    api(`/api/admin/code-limits/user/${id}?days=30`).then((c) => { if (detail.value?.id === id) codeStat.value = c }).catch(() => {})
  } catch (e) {
    fail(e)
    if (!detail.value) dRoute.close()
  }
}
watch(dRoute.id, (id) => {
  if (!id) return
  if (String(detail.value?.id) !== id) detail.value = null
  openUser(Number(id))
}, { immediate: true })
const acct = ref(null)
watch(() => [detail.value?.id, dtab.value], async ([id, t]) => {
  if (t !== 'account' || !id) return
  if (acct.value?.id !== id) acct.value = null
  try {
    acct.value = await api(`/api/admin/users/${id}/account`)
  } catch (e) {
    fail(e)
  }
})
// 内容与行为：提交、评论评分、收藏、反馈、对比、订阅
const content = ref(null)
const moreBusy = ref('')
watch(() => [detail.value?.id, dtab.value], async ([id, t]) => {
  if (t !== 'content' || !id) return
  if (content.value?.id !== id) content.value = null
  try {
    content.value = await api(`/api/admin/users/${id}/content`)
  } catch (e) {
    fail(e)
  }
})
async function loadMore(section) {
  const sec = content.value[section]
  moreBusy.value = section
  try {
    const d = await api(`/api/admin/users/${content.value.id}/content/${section}?page=${sec.page + 1}&page_size=${sec.page_size}`)
    content.value[section] = { ...sec, page: d.page, total: d.total, items: [...sec.items, ...d.items] }
  } catch (e) {
    fail(e)
  } finally {
    moreBusy.value = ''
  }
}
const stars = (n) => (n == null ? '' : `★${n}`)
// 站内消息：发给 TA 的消息记录，客服可以单发一条（带原因，每人每天有上限）
const msgs = ref(null)
const msgKind = ref('admin_message')
const msgForm = ref({ title: '', text: '' })
const msgTemplates = ref([])
const sendingMsg = ref(false)
async function loadMsgs(more = false) {
  const id = detail.value?.id
  if (!id) return
  const page = more ? msgs.value.page + 1 : 1
  try {
    const d = await api(`/api/admin/users/${id}/messages?kind=${msgKind.value}&page=${page}&page_size=20`)
    if (detail.value?.id !== id) return
    msgs.value = more ? { ...d, items: [...msgs.value.items, ...d.items] } : d
  } catch (e) {
    fail(e)
  }
}
watch(() => [detail.value?.id, dtab.value, msgKind.value], ([id, t]) => {
  if (t !== 'messages' || !id) return
  msgs.value = null
  loadMsgs()
  if (!msgTemplates.value.length && hasCap('send_message')) api('/api/admin/reply-templates?scope=user_message').then((d) => (msgTemplates.value = d.items)).catch(() => {})
})
function useMsgTemplate(t) {
  const name = detail.value?.nickname || '你'
  msgForm.value = { title: t.title, text: t.text.replaceAll('{nickname}', name).replaceAll('{id}', detail.value.id) }
}
async function sendMsg() {
  const u = detail.value
  const reason = await askReason({ title: `给「${u.nickname}」发站内消息`, impact: '用户会在铃铛里收到这条消息', templates: ['客服跟进', '通知处理结果', '提醒注意事项'], okText: '发送' })
  if (reason === null) return
  sendingMsg.value = true
  try {
    await api(`/api/admin/users/${u.id}/messages`, { method: 'POST', body: { title: msgForm.value.title.trim(), text: msgForm.value.text.trim(), reason } })
    toast('已发送', 'success')
    msgForm.value = { title: '', text: '' }
    msgKind.value = 'admin_message'
    await loadMsgs()
  } catch (e) {
    fail(e)
  } finally {
    sendingMsg.value = false
  }
}

// 以 TA 的视角只读查看：先填原因开启 15 分钟的查看会话
const viewAs = ref(null)
async function startViewAs() {
  const u = detail.value
  const reason = await askReason({ title: `以「${u.nickname}」的视角查看`, impact: '只读，限时 15 分钟；开启和每次读取都会留日志', templates: ['用户反馈问题，需要复现', '核对用户投诉'], okText: '开始查看' })
  if (reason === null) return
  try {
    viewAs.value = { ...(await api(`/api/admin/users/${u.id}/view-sessions`, { method: 'POST', body: { reason } })), user_id: u.id, name: u.nickname }
  } catch (e) {
    fail(e)
  }
}
// 管理记录：管理员对 TA 的操作 / TA 自己的操作
const logMode = ref('to')
const logs = ref(null)
async function loadLogs() {
  const id = detail.value?.id
  if (!id) return
  logs.value = null
  const p = new URLSearchParams({ page_size: 30 })
  if (logMode.value === 'to') p.set('target_user_id', id)
  else { p.set('user_id', id); p.set('actor', 'user') }
  try {
    const d = await api(`/api/admin/activity?${p}`)
    if (detail.value?.id === id) logs.value = d
  } catch (e) {
    fail(e)
  }
}
watch(() => [detail.value?.id, dtab.value, logMode.value], ([id, t]) => { if (t === 'log' && id) loadLogs() })
// 备注名：只在管理端显示，方便认出是谁
const remarkDraft = ref('')
// 标签直接读详情（?id= 直接打开也能编辑）
const drawerTags = computed(() => detail.value?.tags || null)
function onTagsSaved(tags) {
  detail.value.tags = tags
  const row = uData.value?.items.find((x) => x.id === detail.value.id)
  if (row) row.tags = tags
}
const savingRemark = ref(false)
async function saveRemark() {
  savingRemark.value = true
  try {
    const r = await api(`/api/admin/users/${detail.value.id}/remark`, { method: 'PUT', body: { remark: remarkDraft.value.trim() } })
    detail.value.remark = r.remark
    toast(r.remark ? `已备注为「${r.remark}」` : '已清除备注', 'success')
    loadUsers()
  } catch (e) {
    fail(e)
  } finally {
    savingRemark.value = false
  }
}
const displayName = (u) => (u.username === 'admin' ? 'Admin' : u.nickname)
const fmtQuota = (n) => (n == null ? '未发放' : Math.abs(n) >= 10000 ? `${(n / 10000).toFixed(Math.abs(n) >= 1e6 ? 0 : 1)} 万` : String(n))
const canWrite = computed(() => can('users', 'w'))
const canManage = (u) => canWrite.value && u && u.role === 'user' && !['deleted', 'merged'].includes(u.status)
// 表格列（手机上变卡片）、勾选与批量操作
const uColumns = [
  { key: 'user', label: '用户', mobile: 'title' },
  { key: 'role', label: '身份 / 状态', mobile: 'meta' },
  { key: 'quota_balance', label: 'AI 额度', align: 'right', mobile: 'meta', mlabel: true },
  { key: 'ip', label: '最近 IP / 归属地', hideBelow: 'md', mobile: 'hide' },
  { key: 'created_at', label: '注册', hideBelow: 'lg', mobile: 'hide' },
  { key: 'last_seen_at', label: '最近活跃', align: 'right', mobile: 'meta' },
]
const uSel = useSelection({ rows: computed(() => uData.value?.items || []), total: computed(() => uData.value?.total || 0), params: uParams, selectable: canManage })
const pickTag = (verb) => async (n) => {
  const v = await askChoice({ title: `批量${verb}标签`, impact: `将给 ${n} 个账号${verb}这个标签`, options: tagState.value.items.map((t) => ({ value: t.id, label: t.name })), placeholder: '选择标签', okText: verb })
  return v == null || v === '' ? null : { tag_id: v }
}
const bulkActions = [
  { key: 'add_tag', label: '加标签', icon: 'note', pick: pickTag('添加'), reason: { title: '批量添加标签', impact: (n) => `将给 ${n} 个账号添加标签`, templates: ['内测邀请', '重点跟进', '贡献者'], okText: '添加' },
    run: (scope, reason, params) => runBulk('/api/admin/users/bulk', { action: 'add_tag', scope, reason, params }) },
  { key: 'remove_tag', label: '去标签', icon: 'note', more: true, pick: pickTag('去掉'), reason: { title: '批量去掉标签', impact: (n) => `将去掉 ${n} 个账号的这个标签`, templates: ['内测结束', '标签用错了'], okText: '去掉' },
    run: (scope, reason, params) => runBulk('/api/admin/users/bulk', { action: 'remove_tag', scope, reason, params }) },
  { key: 'disable', label: '批量停用', icon: 'lock', danger: true, reason: { title: '批量停用账号', impact: (n) => `将停用 ${n} 个账号，并退出所有已登录设备`, templates: REASONS.disable, okText: '停用' },
    run: (scope, reason) => runBulk('/api/admin/users/bulk', { action: 'disable', scope, reason }) },
  { key: 'enable', label: '批量启用', icon: 'check', reason: { title: '批量启用账号', impact: (n) => `将启用 ${n} 个账号，恢复登录`, templates: REASONS.enable, okText: '启用' },
    run: (scope, reason) => runBulk('/api/admin/users/bulk', { action: 'enable', scope, reason }) },
]
const isSuper = computed(() => authState.user?.role === 'admin')
// 子管理员不能停用 / 删除，但超级管理员可以改其登录邮箱
const canEditEmail = (u) => canManage(u) || (u && isSuper.value && u.role === 'subadmin' && u.status !== 'deleted')

async function setStatus(u, status) {
  const name = u.nickname
  const off = status === 'disabled'
  const reason = await askReason({
    title: off ? `停用「${name}」？` : `启用「${name}」？`,
    impact: off ? `将停用 1 个账号（${u.account_label || u.email || `#${u.id}`}），并退出所有已登录设备` : `将启用 1 个账号（${u.account_label || u.email || `#${u.id}`}），恢复登录`,
    templates: off ? REASONS.disable : REASONS.enable,
    danger: off,
    okText: off ? '停用' : '启用',
  })
  if (reason === null) return
  try {
    await api(`/api/admin/users/${u.id}/status`, { method: 'POST', body: { status, reason } })
    toast(off ? `已停用「${name}」` : `已启用「${name}」`, 'success')
    await openUser(u.id)
    loadUsers()
  } catch (e) {
    fail(e)
  }
}

async function changeEmail(u) {
  const email = await promptDialog({ title: `修改「${u.nickname}」的登录邮箱`, message: `当前：${u.email}
改后用新邮箱接收验证码、登录；已登录的设备保持登录。`, value: u.email, placeholder: 'name@example.com', okText: '修改' })
  if (!email || email === u.email) return
  try {
    await callVerified(`/api/admin/users/${u.id}/email`, { method: 'PUT', body: { email } }, { action: 'change_email', title: `修改「${u.nickname}」的登录邮箱` })
    toast(`已改为 ${email}`, 'success')
    await openUser(u.id)
    loadUsers()
  } catch (e) {
    fail(e)
  }
}

async function removeUser(u) {
  if (!(await confirmDialog({ title: `删除「${u.nickname}」的账号？`, message: `${u.email}\n收藏会被删除；评论和其提交的条目保留，显示为「已注销用户」；邮箱可以重新注册。此操作不能撤销。`, okText: '删除账号', danger: true }))) return
  try {
    await callVerified(`/api/admin/users/${u.id}`, { method: 'DELETE' }, { action: 'delete_user', title: `删除「${u.nickname}」的账号` })
    toast(`已删除「${u.nickname}」的账号`, 'success')
    dRoute.close()
    loadUsers()
  } catch (e) {
    fail(e)
  }
}

// ---------------------------------------------------------------- 游客
const gq = ref('')
const gPage = ref(1)
const gData = ref(null)
async function loadGuests(more = false) {
  gPage.value = more ? gPage.value + 1 : 1
  try {
    const d = await api(`/api/admin/analytics/visitors?${new URLSearchParams({ kind: 'guest', q: gq.value, page: gPage.value })}`)
    gData.value = more ? { ...d, items: [...gData.value.items, ...d.items] } : d
  } catch (e) {
    fail(e)
  }
}

// ---------------------------------------------------------------- IP 封禁
const bans = ref(null)
const banForm = ref({ ip: '', reason: '', days: '' })
const dayOptions = [{ value: '', label: '永久' }, { value: 1, label: '1 天' }, { value: 7, label: '7 天' }, { value: 30, label: '30 天' }, { value: 365, label: '1 年' }]
async function loadBans() {
  try {
    bans.value = await api('/api/admin/ip-bans')
  } catch (e) {
    fail(e)
  }
}
async function addBan(ip, reason = '') {
  const body = { ip: (ip || banForm.value.ip).trim(), reason: ip ? reason : banForm.value.reason, days: ip ? null : banForm.value.days || null }
  if (!body.ip) return
  try {
    const r = await api('/api/admin/ip-bans', { method: 'POST', body })
    toast(`已封禁 ${r.cidr}`, 'success')
    banForm.value = { ip: '', reason: '', days: '' }
    loadBans()
  } catch (e) {
    fail(e)
  }
}
async function quickBan(ip, who) {
  const reason = await promptDialog({ title: `封禁 IP ${ip}？`, message: `封禁后这个 IP 访问全站都会被拒绝（${who}）。可以在「IP 封禁」里解除。`, placeholder: '原因（可选）', okText: '封禁', danger: true })
  if (reason === null) return
  await addBan(ip, reason || '')
}
async function removeBan(b) {
  if (!(await confirmDialog({ title: `解除对 ${b.cidr} 的封禁？`, okText: '解除' }))) return
  try {
    await api(`/api/admin/ip-bans/${b.id}`, { method: 'DELETE' })
    toast(`已解除 ${b.cidr}`, 'success')
    loadBans()
  } catch (e) {
    fail(e)
  }
}

let t
watch(() => uParams.value.toString(), () => loadUsers())
watch(gq, () => {
  clearTimeout(t)
  t = setTimeout(() => loadGuests(), 250)
})
watch(tab, (v) => {
  if (v === 'users' && !uData.value) loadUsers()
  if (v === 'guests' && !gData.value) loadGuests()
  if (v === 'bans' && !bans.value) loadBans()
}, { immediate: true })
</script>

<template>
  <div>
    <div class="flex flex-wrap items-end gap-3">
      <div>
        <h1 class="m-0 text-xl font-semibold">用户管理</h1>
      </div>
      <div class="seg ml-auto">
        <button v-for="x in TABS" :key="x[0]" :class="{ on: tab === x[0] }" @click="setTab(x[0])">{{ x[1] }}</button>
      </div>
    </div>

    <!-- 注册用户 -->
    <template v-if="tab === 'users'">
      <div v-if="uData" class="mt-5 grid grid-cols-2 gap-3.5 lg:grid-cols-4">
        <div v-for="k in [['users', '普通用户'], ['staff', '管理员'], ['disabled', '已停用'], ['guests', '游客（浏览器）']]" :key="k[0]" class="card px-[18px] py-3.5">
          <p class="m-0 text-[13px] text-mute">{{ k[1] }}</p>
          <b class="mt-1 block text-2xl tabular-nums" :class="{ 'text-bad': k[0] === 'disabled' && uData.counts.disabled }">{{ uData.counts[k[0]] }}</b>
        </div>
      </div>
      <section class="card mt-3.5">
        <AFilterBar :filters="uf" :fields="uFields" :active-count="uActive" @reset="uReset"><template #extra><button class="btn" @click="showTags = true"><Icon name="note" :size="14" />标签</button><AViewMenu scope="users" :query="uQuery" @apply="uApply" /></template></AFilterBar>
        <p v-if="uf.client_version" class="m-0 flex items-center gap-2 border-b border-line bg-primary-soft px-[18px] py-2 text-[13px] text-primary">最近登录的版本：<span class="font-mono">{{ uf.client_version === 'unknown' ? '未知' : uf.client_version }}</span><button class="ml-auto underline" @click="uf.client_version = ''">去掉</button></p>
        <ATable :columns="uColumns" :rows="uData?.items || []" :loading="!uData" :selection="canWrite ? uSel : null" clickable empty-text="没有符合条件的用户" @row-click="(u) => dRoute.open(u.id)">
          <template #cell-user="{ row: u }">
            <span class="flex items-center gap-2.5"><UserAvatar :user="u" :size="28" />
              <span class="min-w-0"><b class="font-semibold">{{ u.remark || displayName(u) }}</b><span v-if="u.remark" class="ml-1 text-xs text-mute">{{ displayName(u) }}</span><span class="block truncate text-xs text-mute">{{ u.account_label || u.email || '—' }}</span><span v-if="u.tags?.length" class="mt-0.5 flex flex-wrap gap-1"><span v-for="t in u.tags" :key="t.id" class="tag !h-[18px] !px-1.5 !text-[11px]" :class="TAG_COLOR[t.color]">{{ t.name }}</span></span></span>
            </span>
          </template>
          <template #cell-role="{ row: u }"><span class="flex flex-wrap gap-1"><span class="tag" :class="ROLE[u.role]?.[1]">{{ ROLE[u.role]?.[0] || u.role }}</span><span class="tag" :class="STATUS[u.status]">{{ u.status_label }}</span></span></template>
          <template #cell-quota_balance="{ row: u }"><span class="whitespace-nowrap tabular-nums" :class="u.quota_balance != null && u.quota_balance <= 0 ? 'text-bad' : u.quota_balance == null ? 'text-mute' : ''">{{ fmtQuota(u.quota_balance) }}</span></template>
          <template #cell-ip="{ row: u }"><template v-if="u.ip">{{ u.geo || '未知地区' }}<span class="block font-mono text-xs text-mute">{{ u.ip }}</span></template><span v-else class="text-mute">—</span></template>
          <template #cell-created_at="{ row: u }"><span class="text-xs whitespace-nowrap text-mute">{{ formatTime(u.created_at, false) }}</span></template>
          <template #cell-last_seen_at="{ row: u }"><span class="text-xs whitespace-nowrap text-mute">{{ u.last_seen_at ? timeAgo(u.last_seen_at) : '从未登录' }}</span></template>
        </ATable>
        <div v-if="uData" class="flex items-center border-t border-line px-[18px] py-3 text-xs text-mute">
          共 {{ uData.total }} 人
          <span class="ml-auto flex items-center gap-2">
            <AExport endpoint="/api/admin/users/export" :params="uParams" :count="uData.total" email />
            <button v-if="uData.items.length < uData.total" class="btn btn-sm" @click="loadUsers(true)">加载更多</button>
          </span>
        </div>
      </section>
      <ABulkBar v-if="canWrite" :selection="uSel" :actions="bulkActions" noun="个账号" @done="loadUsers()" />
    </template>

    <!-- 游客 -->
    <section v-else-if="tab === 'guests'" class="card mt-5">
      <div class="flex flex-wrap items-center gap-2.5 border-b border-line p-3.5">
        <input v-model="gq" type="search" class="input sm:max-w-sm" placeholder="搜索 IP、地区、设备" aria-label="搜索游客" />
      </div>
      <div v-if="!gData" class="card-bd"><div class="skeleton h-60" /></div>
      <p v-else-if="!gData.items.length" class="empty">没有符合条件的游客</p>
      <div v-else class="overflow-x-auto">
        <table class="tbl">
          <thead><tr><th>游客</th><th>位置 / IP</th><th class="hidden md:table-cell">设备</th><th class="hidden lg:table-cell">访问 / 行为</th><th class="text-right">最近活跃</th><th /></tr></thead>
          <tbody>
            <tr v-for="v in gData.items" :key="v.vid">
              <td><span class="flex items-center gap-2"><span class="h-2 w-2 rounded-full" :class="v.online ? 'bg-ok' : 'bg-line'" />游客 <span class="font-mono text-xs text-mute">{{ v.vid.slice(2, 8) }}</span></span></td>
              <td>{{ v.geo || '未知地区' }}<span class="block font-mono text-xs text-mute">{{ v.ip }}</span></td>
              <td class="hidden text-ink-2 md:table-cell">{{ v.device }}</td>
              <td class="hidden text-ink-2 tabular-nums lg:table-cell">{{ v.visits }} 次 / {{ v.events }}</td>
              <td class="text-right text-xs whitespace-nowrap text-mute">{{ timeAgo(v.last_seen) }}</td>
              <td class="text-right whitespace-nowrap">
                <RouterLink :to="{ path: '/visitors', query: { vid: v.vid } }" class="btn btn-sm">轨迹</RouterLink>
                <button v-if="v.ip" class="btn btn-sm btn-danger ml-1.5" @click="quickBan(v.ip, `游客 ${v.vid.slice(2, 8)}`)">封禁 IP</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="gData" class="flex items-center border-t border-line px-[18px] py-3 text-xs text-mute">
        共 {{ gData.total }} 位游客
        <button v-if="gData.items.length < gData.total" class="btn btn-sm ml-auto" @click="loadGuests(true)">加载更多</button>
      </div>
    </section>

    <!-- IP 封禁 -->
    <template v-else>
      <form class="card mt-5 grid gap-2.5 p-3.5 sm:grid-cols-[1fr_1fr_130px_auto]" @submit.prevent="addBan()">
        <input v-model="banForm.ip" class="input" placeholder="IP 或网段，如 1.2.3.4、1.2.3.0/24" aria-label="要封禁的 IP" required />
        <input v-model="banForm.reason" class="input" placeholder="原因（可选）" aria-label="封禁原因" maxlength="200" />
        <ASelect v-model="banForm.days" :options="dayOptions" label="封禁时长" />
        <button class="btn btn-primary"><Icon name="lock" :size="14" />封禁</button>
      </form>
      <section class="card mt-3.5">
        <div class="card-hd"><h2>封禁列表</h2><span v-if="bans" class="text-xs text-mute">{{ bans.length }} 条 · 被封的 IP 访问全站都会看到「禁止访问」</span></div>
        <div v-if="!bans" class="card-bd"><div class="skeleton h-32" /></div>
        <p v-else-if="!bans.length" class="empty">没有封禁的 IP</p>
        <table v-else class="tbl">
          <thead><tr><th>IP / 网段</th><th>归属地</th><th class="hidden md:table-cell">原因</th><th class="hidden lg:table-cell">操作人 / 时间</th><th>到期</th><th /></tr></thead>
          <tbody>
            <tr v-for="b in bans" :key="b.id" :class="{ 'opacity-50': b.expired }">
              <td class="font-mono">{{ b.single ? b.cidr.split('/')[0] : b.cidr }}</td>
              <td>{{ b.geo || '—' }}</td>
              <td class="hidden text-ink-2 md:table-cell">{{ b.reason || '—' }}</td>
              <td class="hidden text-xs text-mute lg:table-cell">{{ b.created_by || '—' }} · {{ formatTime(b.created_at) }}</td>
              <td class="text-xs whitespace-nowrap">{{ b.expires_at ? (b.expired ? '已过期' : formatTime(b.expires_at, false)) : '永久' }}</td>
              <td class="text-right"><button class="btn btn-sm" @click="removeBan(b)">解除</button></td>
            </tr>
          </tbody>
        </table>
      </section>
    </template>

    <!-- 用户详情 -->
    <TagsManager :open="showTags" :can-write="canWrite" @close="showTags = false" @changed="loadUsers()" />
    <ADrawer :open="!!dRoute.id.value" label="用户详情" @close="dRoute.close()">
      <template #header>
        <p v-if="!detail" class="m-0 text-mute">加载中…</p>
        <div v-else class="flex items-center gap-3">
          <UserAvatar :user="detail" :size="40" />
          <div class="min-w-0">
            <p class="m-0 font-semibold">{{ detail.remark || displayName(detail) }}<span v-if="detail.remark" class="ml-1 text-xs font-normal text-mute">{{ displayName(detail) }}</span>
              <span class="tag ml-1" :class="ROLE[detail.role]?.[1]">{{ ROLE[detail.role]?.[0] }}</span>
              <span class="tag ml-1" :class="STATUS[detail.status]">{{ detail.status_label }}</span></p>
            <p class="m-0 truncate text-xs text-mute">{{ detail.account_label || detail.email || '—' }}<template v-if="detail.email"> · #{{ detail.id }}</template></p>
          </div>
        </div>
      </template>
      <div v-if="!detail" class="skeleton h-72" />
      <template v-else>
        <div class="mb-4 flex flex-wrap items-center gap-2"><div class="seg max-w-full overflow-x-auto"><button v-for="t in DTABS" :key="t[0]" :class="{ on: dtab === t[0] }" @click="setDtab(t[0])">{{ t[1] }}</button></div><button v-if="hasCap('view_as_user') && detail.status !== 'deleted'" class="btn btn-sm ml-auto" @click="startViewAs"><Icon name="eye" :size="14" />以 TA 的视角查看</button></div>
        <template v-if="dtab === 'overview'">
        <dl class="m-0 grid grid-cols-[76px_1fr] gap-x-3 gap-y-2 text-[13px]">
          <dt class="text-mute">注册时间</dt><dd class="m-0">{{ formatTime(detail.created_at) }}</dd>
          <dt class="text-mute">最近登录</dt><dd class="m-0">{{ detail.last_login_at ? formatTime(detail.last_login_at) : '从未登录' }}</dd>
          <dt v-if="codeStat" class="text-mute">验证码</dt><dd v-if="codeStat" class="m-0">近 30 天发送 {{ codeStat.sent ?? '未知' }} 次<span v-if="codeStat.limited" class="tag tag-warn ml-2">被限频 {{ codeStat.limited }} 次</span></dd>
          <dt class="text-mute">最近位置</dt><dd class="m-0">{{ detail.geo || '—' }} <span class="font-mono text-xs text-mute">{{ detail.ip }}</span></dd>
          <dt class="self-center text-mute">备注名</dt>
          <dd class="m-0">
            <form class="flex gap-1.5" @submit.prevent="saveRemark">
              <label class="sr-only" for="u-remark">备注名</label>
              <input id="u-remark" v-model="remarkDraft" class="input h-8" maxlength="60" placeholder="只有管理员能看到，例如：老客户·张三" />
              <button class="btn btn-sm shrink-0" :disabled="savingRemark || remarkDraft.trim() === (detail.remark || '')">保存</button>
            </form>
          </dd>
          <template v-if="drawerTags"><dt class="self-center text-mute">标签</dt><dd class="m-0"><UserTagsEditor :user-id="detail.id" :tags="drawerTags" :can-write="canWrite" @saved="onTagsSaved" /></dd></template>
        </dl>
        <div class="mt-4 grid grid-cols-5 gap-2 text-center">
          <div v-for="k in [['submissions', '提交'], ['comments', '评论'], ['favorites', '收藏'], ['feedback', '反馈'], ['compares', '对比']]" :key="k[0]" class="rounded-lg bg-subtle py-2">
            <b class="block text-lg tabular-nums">{{ detail.stats[k[0]] }}</b><span class="text-xs text-mute">{{ k[1] }}</span>
          </div>
        </div>

        <UserQuota v-if="detail.status !== 'deleted'" :user-id="detail.id" :name="detail.remark || displayName(detail)" @changed="(b) => { detail.quota_balance = b; loadUsers() }" />


        <template v-if="detail.visitors.length">
          <h3 class="mt-5 mb-2 text-[13px] font-semibold">浏览器（访客记录）</h3>
          <ul class="m-0 list-none p-0">
            <li v-for="v in detail.visitors" :key="v.vid" class="flex flex-wrap items-center gap-x-2.5 border-b border-dashed border-line py-2 text-[13px] last:border-0">
              <span>{{ v.device }}</span><span class="text-ink-2">{{ v.geo }}</span>
              <span v-if="v.converted_at" class="tag tag-warn">游客转注册</span>
              <RouterLink :to="{ path: '/visitors', query: { vid: v.vid } }" class="ml-auto text-xs text-primary hover:underline">访问轨迹</RouterLink>
            </li>
          </ul>
        </template>

        <template v-if="detail.submissions.length">
          <h3 class="mt-5 mb-2 text-[13px] font-semibold">提交的条目</h3>
          <ul class="m-0 list-none p-0">
            <li v-for="i in detail.submissions" :key="i.id" class="flex items-center gap-2 py-1.5 text-[13px]">
              <a :href="`/items/${i.id}`" target="_blank" class="truncate hover:text-primary">{{ i.name }}</a>
              <span class="tag tag-gray ml-auto">{{ i.status_label }}</span>
            </li>
          </ul>
        </template>

        <h3 class="mt-5 mb-2 text-[13px] font-semibold">最近操作</h3>
        <p v-if="!detail.activity.length" class="m-0 text-[13px] text-mute">没有操作记录</p>
        <ul class="m-0 list-none p-0">
          <li v-for="a in detail.activity" :key="a.id" class="border-b border-dashed border-line py-2 text-[13px] last:border-0">
            <span class="tag tag-blue mr-1.5">{{ a.action }}</span>{{ a.summary }}
            <span class="block text-xs text-mute">{{ formatTime(a.created_at) }}<template v-if="a.ip"> · {{ a.geo || '未知地区' }} · {{ a.ip }}</template></span>
          </li>
        </ul>
        </template>
        <template v-else-if="dtab === 'account'">
          <p v-if="!acct" class="m-0 text-mute">加载中…</p>
          <template v-else>
            <h3 class="m-0 mb-2 text-[13px] font-semibold">身份</h3>
            <dl class="m-0 grid grid-cols-[76px_1fr] gap-x-3 gap-y-2 text-[13px]">
              <dt class="text-mute">账号类型</dt><dd class="m-0"><span class="tag tag-blue">{{ acct.kind_label }}</span></dd>
              <dt class="text-mute">邮箱</dt><dd class="m-0 break-all">{{ acct.identities.email || '未绑定' }}</dd>
              <dt class="text-mute">用户名</dt><dd class="m-0">{{ acct.identities.username || '—' }}</dd>
              <dt class="text-mute">密码</dt><dd class="m-0">{{ acct.identities.has_password ? '已设置' : '未设置' }}</dd>
              <dt class="text-mute">微信</dt>
              <dd class="m-0">
                <template v-if="acct.identities.wechat.bound">已绑定 <span class="font-mono text-xs text-mute">{{ acct.identities.wechat.openid }}</span><span v-if="acct.identities.wechat.unionid" class="tag tag-gray ml-1.5">有 unionid</span></template>
                <template v-else>未绑定</template>
              </dd>
              <dt class="text-mute">注册渠道</dt><dd class="m-0">{{ acct.signup_channel_label }}</dd>
            </dl>

            <h3 class="mt-5 mb-2 text-[13px] font-semibold">合并关系</h3>
            <p v-if="!acct.merged_into && !acct.merged_from.length" class="m-0 text-[13px] text-mute">没有合并记录</p>
            <ul class="m-0 list-none p-0 text-[13px]">
              <li v-if="acct.merged_into" class="flex items-center gap-2 py-1.5"><span class="tag tag-gray">已并入</span><button class="text-primary hover:underline" @click="dRoute.open(acct.merged_into.id)">{{ acct.merged_into.label }}</button></li>
              <li v-for="m in acct.merged_from" :key="m.id" class="flex items-center gap-2 py-1.5"><span class="tag tag-gray">并入的账号</span><button class="text-primary hover:underline" @click="dRoute.open(m.id)">{{ m.label }}</button><span class="text-xs text-mute">{{ m.kind_label }}</span></li>
            </ul>

            <h3 class="mt-5 mb-2 text-[13px] font-semibold">绑定与账号记录</h3>
            <p v-if="!acct.timeline.length" class="m-0 text-[13px] text-mute">没有记录</p>
            <ul class="m-0 list-none p-0">
              <li v-for="t in acct.timeline" :key="t.id" class="border-b border-dashed border-line py-2 text-[13px] last:border-0">
                <span class="tag mr-1.5" :class="t.result === 'failed' ? 'tag-bad' : 'tag-blue'">{{ t.action_label }}</span><span :class="t.result === 'failed' ? 'text-bad' : ''">{{ t.summary }}</span>
                <span v-if="t.result === 'failed' && t.message" class="block text-xs text-bad">{{ t.message }}</span>
                <span v-if="t.reason" class="block text-xs text-ink-2">原因：{{ t.reason }}</span>
                <span class="block text-xs text-mute">{{ formatTime(t.created_at) }}</span>
              </li>
            </ul>

            <h3 class="mt-5 mb-2 text-[13px] font-semibold">扫码记录</h3>
            <p v-if="!acct.qr_logins.length" class="m-0 text-[13px] text-mute">没有扫码记录</p>
            <ul class="m-0 list-none p-0">
              <li v-for="(q, i) in acct.qr_logins" :key="i" class="flex flex-wrap items-center gap-x-2.5 gap-y-1 border-b border-dashed border-line py-2 text-[13px] last:border-0">
                <span>{{ q.purpose_label }}</span><span class="tag" :class="q.status === 'done' ? 'tag-ok' : 'tag-gray'">{{ q.status_label }}</span><span class="text-xs text-mute">{{ q.role }}</span>
                <span class="ml-auto text-xs text-mute">{{ timeAgo(q.created_at) }}</span>
              </li>
            </ul>

            <h3 class="mt-5 mb-2 text-[13px] font-semibold">各端登录次数</h3>
            <p v-if="!Object.keys(acct.logins_by_client).length" class="m-0 text-[13px] text-mute">没有登录记录</p>
            <p class="m-0 flex flex-wrap gap-1.5"><span v-for="(n, k) in acct.logins_by_client" :key="k" class="tag tag-gray">{{ k }} {{ n }}</span></p>
          </template>

        <h3 class="mt-5 mb-2 text-[13px] font-semibold">登录设备与 IP</h3>
        <p v-if="!detail.sessions.length" class="m-0 text-[13px] text-mute">没有登录记录</p>
        <ul class="m-0 list-none p-0">
          <li v-for="s in detail.sessions" :key="s.id" class="flex flex-wrap items-center gap-x-2.5 gap-y-1 border-b border-dashed border-line py-2 text-[13px] last:border-0">
            <span class="h-2 w-2 rounded-full" :class="s.active ? 'bg-ok' : 'bg-line'" :title="s.active ? '仍在登录' : '已退出'" />
            <span>{{ s.device }}</span><span class="text-ink-2">{{ s.geo || '未知地区' }}</span><span class="font-mono text-xs text-mute">{{ s.ip }}</span>
            <span class="ml-auto text-xs text-mute">{{ timeAgo(s.last_seen_at) }}</span>
            <button v-if="s.ip && canManage(detail)" class="btn btn-sm btn-danger" @click="quickBan(s.ip, detail.nickname)">封禁 IP</button>
          </li>
        </ul>
        </template>
        <template v-else-if="dtab === 'content'">
          <div v-if="!content" class="skeleton h-72" />
          <template v-else>
            <p class="m-0 mb-3 flex gap-3 text-xs"><RouterLink :to="{ path: '/ingest-tasks', query: { user_id: content.id } }" class="text-primary hover:underline">TA 的收录任务</RouterLink><RouterLink :to="{ path: '/comments', query: { user_id: content.id, status: 'all' } }" class="text-primary hover:underline">TA 的评论</RouterLink></p>
            <h3 class="m-0 mb-2 flex items-baseline gap-2 text-[13px] font-semibold">提交的条目<span class="font-normal text-mute tabular-nums">{{ content.submissions.total }}</span></h3>
            <p v-if="!content.submissions.items.length" class="m-0 text-[13px] text-mute">没有提交</p>
            <ul class="m-0 list-none p-0">
              <li v-for="i in content.submissions.items" :key="i.id" class="flex items-center gap-2 border-b border-dashed border-line py-2 text-[13px] last:border-0">
                <RouterLink :to="{ path: '/content', query: { id: i.id } }" class="min-w-0 flex-1 truncate hover:text-primary">{{ i.name }}</RouterLink>
                <span class="tag tag-gray">{{ i.status_label }}</span><span class="hidden text-xs whitespace-nowrap text-mute sm:inline">{{ formatTime(i.created_at, false) }}</span>
              </li>
            </ul>
            <button v-if="content.submissions.items.length < content.submissions.total" class="btn btn-sm mt-2" :disabled="moreBusy === 'submissions'" @click="loadMore('submissions')">加载更多</button>

            <h3 class="mt-5 mb-2 flex flex-wrap items-baseline gap-x-2 text-[13px] font-semibold">评论与评分<span class="font-normal text-mute tabular-nums">{{ content.comments.total }}</span>
              <span class="font-normal text-mute">平均 {{ content.comments.avg_rating == null ? '—' : content.comments.avg_rating }}<template v-if="content.comments.rated_count"> · {{ content.comments.rated_count }} 条评分</template></span></h3>
            <p v-if="!content.comments.items.length" class="m-0 text-[13px] text-mute">没有评论</p>
            <ul class="m-0 list-none p-0">
              <li v-for="c in content.comments.items" :key="c.id" class="border-b border-dashed border-line py-2 text-[13px] last:border-0">
                <span class="flex flex-wrap items-center gap-1.5">
                  <RouterLink :to="{ path: '/content', query: { id: c.item.id } }" class="font-medium hover:text-primary">{{ c.item.name }}</RouterLink>
                  <b v-if="c.rating != null" class="text-warn">{{ stars(c.rating) }}</b>
                  <span class="tag" :class="c.status === 'visible' ? 'tag-ok' : 'tag-warn'">{{ c.status_label }}</span>
                  <span class="ml-auto flex items-center gap-2 text-xs text-mute">{{ formatTime(c.created_at, false) }}<RouterLink :to="{ path: '/comments', query: { id: c.id } }" class="text-primary hover:underline">处理</RouterLink></span>
                </span>
                <span v-if="c.content" class="mt-0.5 block break-words text-ink-2">{{ c.content }}</span>
                <span v-if="c.review_reason" class="mt-0.5 block text-xs text-warn">审核：{{ c.review_reason }}</span>
              </li>
            </ul>
            <button v-if="content.comments.items.length < content.comments.total" class="btn btn-sm mt-2" :disabled="moreBusy === 'comments'" @click="loadMore('comments')">加载更多</button>

            <h3 class="mt-5 mb-2 flex items-baseline gap-2 text-[13px] font-semibold">收藏<span class="font-normal text-mute tabular-nums">{{ content.favorites.total }}</span></h3>
            <p v-if="content.favorites.by_category.length" class="m-0 mb-2 flex flex-wrap gap-1.5"><span v-for="c in content.favorites.by_category" :key="c.name" class="tag tag-gray">{{ c.name }} {{ c.count }}</span></p>
            <p v-if="!content.favorites.total" class="m-0 text-[13px] text-mute">没有收藏</p>
            <ul v-if="content.favorites.folders.length" class="m-0 list-none p-0">
              <li v-for="f in content.favorites.folders" :key="f.id" class="flex items-center gap-2 border-b border-dashed border-line py-2 text-[13px] last:border-0">
                <span class="min-w-0 flex-1 truncate">{{ f.emoji }} {{ f.name }}</span><span class="text-xs text-mute tabular-nums">{{ f.count }} 个</span>
                <span class="tag" :class="f.share_status === 'sharing' ? 'tag-blue' : 'tag-gray'">{{ f.share_status === 'sharing' ? '分享中' : '私有' }}</span>
              </li>
            </ul>

            <h3 class="mt-5 mb-2 flex items-baseline gap-2 text-[13px] font-semibold">反馈<span class="font-normal text-mute tabular-nums">{{ content.feedback.total }}</span></h3>
            <p v-if="!content.feedback.items.length" class="m-0 text-[13px] text-mute">没有反馈</p>
            <ul class="m-0 list-none p-0">
              <li v-for="f in content.feedback.items" :key="f.id" class="flex items-center gap-2 border-b border-dashed border-line py-2 text-[13px] last:border-0">
                <span class="tag tag-blue">{{ f.category_label }}</span>
                <RouterLink :to="{ path: '/feedback', query: { id: f.id } }" class="min-w-0 flex-1 truncate hover:text-primary">{{ f.summary }}</RouterLink>
                <span class="tag" :class="f.status === 'new' ? 'tag-warn' : 'tag-gray'">{{ f.status_label }}</span>
              </li>
            </ul>
            <button v-if="content.feedback.items.length < content.feedback.total" class="btn btn-sm mt-2" :disabled="moreBusy === 'feedback'" @click="loadMore('feedback')">加载更多</button>

            <h3 class="mt-5 mb-2 flex items-baseline gap-2 text-[13px] font-semibold">AI 对比<span class="font-normal text-mute tabular-nums">{{ content.compares.total }}</span></h3>
            <p v-if="!content.compares.items.length" class="m-0 text-[13px] text-mute">没有对比记录</p>
            <ul class="m-0 list-none p-0">
              <li v-for="c in content.compares.items" :key="c.id" class="border-b border-dashed border-line py-2 text-[13px] last:border-0">
                <span class="flex items-center gap-2"><span class="min-w-0 flex-1 truncate">{{ c.names.join(' · ') }}<template v-if="c.count > c.names.length"> 等 {{ c.count }} 个</template></span><span class="tag" :class="c.status === 'done' ? 'tag-ok' : 'tag-gray'">{{ c.status_label }}</span></span>
                <span class="block text-xs text-mute">{{ formatTime(c.created_at) }}</span>
              </li>
            </ul>
            <button v-if="content.compares.items.length < content.compares.total" class="btn btn-sm mt-2" :disabled="moreBusy === 'compares'" @click="loadMore('compares')">加载更多</button>

            <h3 class="mt-5 mb-2 flex items-baseline gap-2 text-[13px] font-semibold">订阅的分类<span class="font-normal text-mute tabular-nums">{{ content.subscriptions.total }}</span>
              <span class="tag" :class="content.subscriptions.daily_push ? 'tag-ok' : 'tag-gray'">{{ content.subscriptions.daily_push ? '每日推送' : '无推送' }}</span></h3>
            <p v-if="!content.subscriptions.items.length" class="m-0 text-[13px] text-mute">没有订阅</p>
            <p class="m-0 flex flex-wrap gap-1.5"><span v-for="c in content.subscriptions.items" :key="c.category_id" class="tag tag-gray">{{ c.name }}</span></p>
          </template>
        </template>
        <template v-else-if="dtab === 'messages'">
          <form v-if="hasCap('send_message') && detail.status === 'active'" class="mb-5 rounded-lg border border-line p-3.5" @submit.prevent="sendMsg">
            <div v-if="msgTemplates.length" class="mb-2 flex flex-wrap gap-1.5"><button v-for="t in msgTemplates" :key="t.id" type="button" class="h-7 rounded-full border border-line px-2.5 text-xs text-ink-2 hover:border-primary hover:text-primary" @click="useMsgTemplate(t)">{{ t.title }}</button></div>
            <input v-model="msgForm.title" class="input" maxlength="40" placeholder="标题（1–40 字）" aria-label="消息标题" />
            <textarea v-model="msgForm.text" rows="3" maxlength="500" class="input mt-2 h-auto resize-y py-2" placeholder="消息内容（{nickname} 会替换成用户昵称）" aria-label="消息内容" />
            <div class="mt-2 flex items-center"><span class="text-xs text-mute tabular-nums">{{ msgForm.text.length }} / 500</span><button class="btn btn-primary ml-auto" :disabled="sendingMsg || !msgForm.title.trim() || !msgForm.text.trim()">{{ sendingMsg ? '发送中…' : '发送给 TA' }}</button></div>
          </form>
          <div class="seg mb-3"><button :class="{ on: msgKind === 'admin_message' }" @click="msgKind = 'admin_message'">管理员发的</button><button :class="{ on: msgKind === 'all' }" @click="msgKind = 'all'">全部消息</button></div>
          <div v-if="!msgs" class="skeleton h-40" />
          <p v-else-if="!msgs.items.length" class="empty">没有消息</p>
          <ul v-else class="m-0 list-none p-0">
            <li v-for="m in msgs.items" :key="m.id" class="border-b border-dashed border-line py-2.5 text-[13px] last:border-0">
              <span class="flex flex-wrap items-center gap-1.5"><span class="tag tag-blue">{{ m.kind_label }}</span><b class="min-w-0 flex-1 truncate font-medium">{{ m.title }}</b><span class="tag" :class="m.read_at ? 'tag-gray' : 'tag-warn'">{{ m.read_at ? '已读' : '未读' }}</span></span>
              <span v-if="m.text" class="mt-1 block break-words whitespace-pre-wrap text-ink-2">{{ m.text }}</span>
              <span class="mt-1 block text-xs text-mute">{{ m.by?.label || '系统' }} · {{ formatTime(m.at) }}<template v-if="m.read_at"> · 已读于 {{ formatTime(m.read_at) }}</template></span>
            </li>
          </ul>
          <button v-if="msgs && msgs.items.length < msgs.total" class="btn btn-sm mt-2" @click="loadMsgs(true)">加载更多</button>
          <p v-if="msgs?.daily_limit" class="m-0 mt-3 text-xs text-mute">每位管理员 24 小时内最多发 {{ msgs.daily_limit }} 条</p>
        </template>
        <template v-else>
          <div class="seg mb-3"><button :class="{ on: logMode === 'to' }" @click="logMode = 'to'">对 TA 的操作</button><button :class="{ on: logMode === 'by' }" @click="logMode = 'by'">TA 的操作</button></div>
          <div v-if="!logs" class="skeleton h-40" />
          <p v-else-if="!logs.items.length" class="empty">没有记录</p>
          <ul v-else class="m-0 list-none p-0">
            <li v-for="r in logs.items" :key="r.id" class="border-b border-dashed border-line py-2.5 text-[13px] last:border-0">
              <span class="mb-1 flex flex-wrap items-center gap-1.5"><span class="tag tag-blue">{{ r.action_label }}</span><span v-if="r.result === 'failed'" class="tag tag-bad">失败</span><span class="text-xs text-mute">{{ formatTime(r.created_at) }}</span></span>
              <ALogItem :row="r" compact />
            </li>
          </ul>
          <p v-if="logs && logs.total > logs.items.length" class="m-0 mt-2 text-xs text-mute">仅显示最近 {{ logs.items.length }} 条，共 {{ logs.total }} 条</p>
        </template>
      </template>
      <template v-if="detail && canManage(detail)" #footer>
        <div class="flex items-center gap-2">
          <button class="btn btn-danger" @click="removeUser(detail)"><Icon name="trash" :size="14" />删除账号</button>
          <button class="btn" @click="changeEmail(detail)"><Icon name="pencil" :size="14" />修改邮箱</button>
          <button v-if="detail.status === 'active'" class="btn btn-danger ml-auto" @click="setStatus(detail, 'disabled')"><Icon name="lock" :size="14" />停用</button>
          <button v-else class="btn btn-primary ml-auto" @click="setStatus(detail, 'active')"><Icon name="check" :size="14" />启用</button>
        </div>
      </template>
      <template v-else-if="detail && detail.role !== 'user'" #footer>
        <div class="flex flex-wrap items-center gap-2">
          <span class="min-w-0 flex-1 text-xs text-mute">{{ ROLE[detail.role]?.[0] || '管理员' }}账号不能停用或删除；要停用，先在「管理员」里取消其管理员身份。</span>
          <button v-if="canEditEmail(detail)" class="btn btn-sm" @click="changeEmail(detail)"><Icon name="pencil" :size="14" />修改邮箱</button>
          <RouterLink v-if="isSuper && detail.role === 'subadmin'" class="btn btn-sm" to="/staff"><Icon name="shield" :size="14" />去管理员页</RouterLink>
        </div>
      </template>
    </ADrawer>
    <ViewAsPanel :open="!!viewAs" :user-id="viewAs?.user_id || 0" :name="viewAs?.name || ''" :session="viewAs" @close="viewAs = null" />
  </div>
</template>
