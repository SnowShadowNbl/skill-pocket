<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { api, formatTime, isCancelled, timeAgo } from '../../api'
import Icon from '../../components/Icon.vue'
import UserAvatar from '../../components/UserAvatar.vue'
import { authState } from '../../composables/auth'
import { toast } from '../../composables/toast'
import ADrawer from '../components/ADrawer.vue'
import ATable from '../components/ATable.vue'
import { askChoice } from '../composables/choice'
import { onActionError } from '../composables/handled'
import { askReason } from '../composables/reason'
import { ROLE_LABEL, hasCap } from '../composables/usePermissions'
import { useDetailRoute } from '../composables/useDetailRoute'
import { callVerified } from '../composables/verify'

// 管理员：角色（管理员 / 内容审核 / 客服 / 只读）、任免、登录记录。超级管理员唯一，不能任命也不能修改；任免和改角色要填原因并做二次验证
const detail = useDetailRoute('id')
const staff = ref(null)
const rolesInfo = ref(null)
const q = ref('')
const candidates = ref([])
const searching = ref(false)
const busy = ref(0)
const logins = ref(null)
const showMatrix = ref(false)
const me = computed(() => authState.user)
const canManage = computed(() => hasCap('manage_staff'))
const ROLE_TAG = { admin: 'tag-blue', subadmin: 'tag-ok', moderator: 'tag-warn', support: 'tag-blue', viewer: 'tag-gray' }
const roleOptions = computed(() => Object.entries(rolesInfo.value?.roles || { subadmin: '管理员' }).map(([k, v]) => ({ value: k, label: v })))
const columns = [
  { key: 'account', label: '账号', mobile: 'title' },
  { key: 'role', label: '角色', mobile: 'meta' },
  { key: 'last', label: '最近登录', hideBelow: 'md', mobile: 'meta' },
  { key: 'actions', label: '', align: 'right', mobile: 'action' },
]
const nameOf = (u) => (u.username === 'admin' ? 'Admin' : u.remark || u.nickname)

async function load() {
  try {
    const [s, r] = await Promise.all([api('/api/admin/staff'), api('/api/admin/staff-roles')])
    staff.value = s
    rolesInfo.value = r
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  }
}

// 已注册用户列表：不输入就按注册时间列出全部，输入邮箱、昵称、备注名过滤（纯微信账号也在里面）
const cPage = ref(1)
const cTotal = ref(0)
async function loadCandidates(more = false) {
  cPage.value = more ? cPage.value + 1 : 1
  searching.value = true
  try {
    const d = await api(`/api/admin/staff/candidates?${new URLSearchParams({ q: q.value.trim(), page: cPage.value })}`)
    candidates.value = more ? [...candidates.value, ...d.items] : d.items
    cTotal.value = d.total
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  } finally {
    searching.value = false
  }
}
let t
watch(q, () => {
  clearTimeout(t)
  t = setTimeout(() => loadCandidates(), 300)
})

const REASONS_STAFF = ['业务需要', '岗位调整', '离职或不再负责']
async function run(u, fn) {
  busy.value = u.id
  try {
    await fn()
    await load()
    if (canManage.value) loadCandidates()
  } catch (e) {
    await onActionError(e, load)
  } finally {
    busy.value = 0
  }
}
async function add(u) {
  const role = await askChoice({ title: `任命「${u.nickname}」`, impact: '任命后对方可以进入管理系统，权限由角色决定', options: roleOptions.value, placeholder: '选择角色', okText: '下一步' })
  if (role == null) return
  const reason = await askReason({ title: `任命「${u.nickname}」为${rolesInfo.value.roles[role]}`, impact: '需要先验证你的邮箱', templates: REASONS_STAFF.slice(0, 2), okText: '任命' })
  if (reason === null) return
  await run(u, async () => {
    await callVerified('/api/admin/staff', { method: 'POST', body: { user_id: u.id, role, reason } }, { action: 'staff_role', title: `任命「${u.nickname}」` })
    toast(`「${u.nickname}」已任命为${rolesInfo.value.roles[role]}`, 'success')
  })
}
async function changeRole(u) {
  const role = await askChoice({ title: `修改「${nameOf(u)}」的角色`, impact: `当前：${u.role_label}`, options: roleOptions.value.filter((o) => o.value !== u.role), placeholder: '选择新角色', okText: '下一步' })
  if (role == null) return
  const reason = await askReason({ title: `把「${nameOf(u)}」改为${rolesInfo.value.roles[role]}`, impact: '需要先验证你的邮箱', templates: REASONS_STAFF, okText: '修改' })
  if (reason === null) return
  await run(u, async () => {
    await callVerified(`/api/admin/staff/${u.id}/role`, { method: 'PUT', body: { role, reason } }, { action: 'staff_role', title: `修改「${nameOf(u)}」的角色` })
    toast('已修改角色', 'success')
  })
}
async function remove(u) {
  const reason = await askReason({ title: `取消「${nameOf(u)}」的管理员身份？`, impact: '取消后变回普通用户，不能再进入管理系统；需要先验证你的邮箱', templates: REASONS_STAFF.slice(1), danger: true, okText: '取消管理员' })
  if (reason === null) return
  await run(u, async () => {
    await callVerified(`/api/admin/staff/${u.id}`, { method: 'DELETE', body: { reason } }, { action: 'staff_role', title: `取消「${nameOf(u)}」的管理员` })
    toast('已取消管理员身份', 'success')
  })
}
const editable = (u) => canManage.value && u.role !== 'admin' && u.id !== me.value?.id

// ------------------------------------------------------------ 登录记录
const target = computed(() => (detail.id.value ? staff.value?.find((s) => String(s.id) === detail.id.value) || null : null))
watch([() => detail.id.value, staff], async ([id]) => {
  logins.value = null
  if (!id || !staff.value) return
  try {
    const mine = String(me.value?.id) === id
    const d = await api(mine ? '/api/admin/me/logins' : `/api/admin/staff/${id}/logins`)
    if (detail.id.value === id) logins.value = d.items
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
    detail.close()
  }
}, { immediate: true })

// ------------------------------------------------------------ 角色权限一览
const matrixRows = computed(() => (rolesInfo.value ? Object.entries(rolesInfo.value.modules) : []))
const matrixRoles = computed(() => (rolesInfo.value ? Object.entries(rolesInfo.value.labels) : []))

onMounted(() => {
  load()
  if (canManage.value) loadCandidates()
})
</script>

<template>
  <div>
    <div class="flex flex-wrap items-center gap-3">
      <h1 class="m-0 text-xl font-semibold">管理员</h1>
      <span class="ml-auto flex gap-2">
        <button class="btn" :aria-expanded="showMatrix" @click="showMatrix = !showMatrix"><Icon name="shield" :size="14" />角色权限</button>
        <RouterLink v-if="me" :to="{ path: '/staff', query: { id: me.id } }" class="btn">我的登录记录</RouterLink>
      </span>
    </div>

    <section v-if="showMatrix && rolesInfo" class="card mt-4">
      <div class="overflow-x-auto">
        <table class="tbl">
          <thead><tr><th>模块</th><th v-for="[k, name] in matrixRoles" :key="k" class="text-center">{{ name }}</th></tr></thead>
          <tbody>
            <tr v-for="[mk, mname] in matrixRows" :key="mk">
              <td class="whitespace-nowrap">{{ mname }}</td>
              <td v-for="[k] in matrixRoles" :key="k" class="text-center">
                <span v-if="(rolesInfo.matrix[k] || {})[mk] === 'w'" class="tag tag-ok">读写</span>
                <span v-else-if="(rolesInfo.matrix[k] || {})[mk] === 'r'" class="tag tag-gray">只读</span>
                <span v-else class="text-mute">—</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section v-if="canManage" class="card mt-4">
      <div class="card-hd"><h2>任命管理员</h2><span class="text-xs text-mute">从已注册的用户里选 · 共 {{ cTotal }} 人</span></div>
      <div class="border-b border-line p-3.5">
        <div class="relative">
          <Icon name="search" :size="16" class="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-mute" />
          <input v-model="q" type="search" class="input h-10 pl-9" placeholder="按邮箱、昵称或备注名筛选" aria-label="筛选用户" />
        </div>
      </div>
      <div v-if="searching && !candidates.length" class="card-bd"><div class="skeleton h-24" /></div>
      <p v-else-if="!candidates.length" class="empty">{{ q.trim() ? '没有找到这个用户（对方需要先在主站注册）' : '还没有可以任命的注册用户' }}</p>
      <ul v-else class="m-0 max-h-[420px] list-none overflow-y-auto p-0">
        <li v-for="u in candidates" :key="u.id" class="flex items-center gap-3 border-b border-line px-[18px] py-2.5 last:border-0">
          <UserAvatar :user="u" :size="28" />
          <div class="min-w-0 flex-1"><b class="font-semibold">{{ u.remark || u.nickname }}</b><span v-if="u.remark" class="ml-1 text-xs text-mute">{{ u.nickname }}</span><span class="block truncate text-xs text-mute">{{ u.account_label || u.email }}</span></div>
          <button class="btn btn-sm btn-primary" :disabled="busy === u.id" @click="add(u)"><Icon name="plus" :size="14" />任命</button>
        </li>
        <li v-if="candidates.length < cTotal" class="flex justify-center py-2.5"><button class="btn btn-sm" :disabled="searching" @click="loadCandidates(true)">加载更多</button></li>
      </ul>
    </section>

    <section class="card mt-4">
      <div class="card-hd"><h2>管理员列表</h2><span v-if="staff" class="text-xs text-mute">{{ staff.length }} 人</span></div>
      <ATable :columns="columns" :rows="staff || []" :loading="!staff" clickable empty-text="没有管理员" @row-click="(u) => detail.open(u.id)">
        <template #cell-account="{ row: u }">
          <span class="flex items-center gap-2.5"><UserAvatar :user="u" :size="28" />
            <span class="min-w-0"><b class="font-semibold">{{ nameOf(u) }}</b><span v-if="u.id === me?.id" class="ml-1.5 text-xs text-mute">（你）</span><span class="block truncate text-xs text-mute">{{ u.account_label || u.email || '用户名 admin' }}</span></span>
          </span>
        </template>
        <template #cell-role="{ row: u }"><span class="tag" :class="ROLE_TAG[u.role]">{{ u.role_label || ROLE_LABEL[u.role] }}</span></template>
        <template #cell-last="{ row: u }"><span class="text-ink-2">{{ u.last_login_at ? timeAgo(u.last_login_at) : '从未登录' }}</span></template>
        <template #cell-actions="{ row: u }">
          <span v-if="editable(u)" class="flex justify-end gap-1.5" @click.stop>
            <button class="btn btn-sm" :disabled="busy === u.id" @click="changeRole(u)">改角色</button>
            <button class="btn btn-sm btn-danger" :disabled="busy === u.id" @click="remove(u)">取消</button>
          </span>
        </template>
      </ATable>
    </section>

    <ADrawer :open="!!detail.id.value" label="登录记录" @close="detail.close()">
      <template #header>
        <p v-if="!target" class="m-0 text-mute">加载中…</p>
        <div v-else>
          <p class="m-0 font-semibold">{{ nameOf(target) }}<span class="tag ml-2" :class="ROLE_TAG[target.role]">{{ target.role_label || ROLE_LABEL[target.role] }}</span></p>
          <p class="m-0 truncate text-xs text-mute">登录记录</p>
        </div>
      </template>
      <div v-if="!logins" class="skeleton h-60" />
      <p v-else-if="!logins.length" class="empty">没有登录记录</p>
      <ul v-else class="m-0 list-none p-0">
        <li v-for="l in logins" :key="l.id" class="border-b border-dashed border-line py-2.5 text-[13px] last:border-0">
          <span class="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span class="h-2 w-2 rounded-full" :class="l.active ? 'bg-ok' : 'bg-line'" :title="l.active ? '仍在登录' : '已退出'" />
            <b class="font-medium">{{ l.client_label || '未知' }}</b><span v-if="l.client_version" class="font-mono text-xs text-mute">{{ l.client_version }}</span>
            <span v-if="l.method_label" class="tag tag-gray">{{ l.method_label }}</span>
            <span v-if="l.new_device" class="tag tag-warn">新设备</span>
            <time class="ml-auto text-xs text-mute">{{ formatTime(l.at) }}</time>
          </span>
          <span class="mt-0.5 block text-xs text-ink-2">{{ l.geo || '未知地区' }} <span class="font-mono text-mute">{{ l.ip }}</span> · {{ l.device }}</span>
        </li>
      </ul>
    </ADrawer>
  </div>
</template>
