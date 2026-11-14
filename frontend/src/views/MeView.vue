<script setup>
import { useItemLink } from '../composables/itemLink'
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'
import { api, authHeaders, formatTime } from '../api'
import Icon from '../components/Icon.vue'
import ItemCard from '../components/ItemCard.vue'
import LogsPanel from '../components/LogsPanel.vue'
import MyFeedback from '../components/MyFeedback.vue'
import MyQuota from '../components/MyQuota.vue'
import { goCollect } from '../composables/collect'
import CompareModeToggle from '../components/CompareModeToggle.vue'
import OtpInput from '../components/OtpInput.vue'
import UserAvatar, { AVATAR_KEYS } from '../components/UserAvatar.vue'
import { authState, clearSession, isAdminUser, requireLogin, setSession } from '../composables/auth'
import { meta } from '../composables/meta'
import WxQrPanel from '../components/WxQrPanel.vue'
import { confirmDialog } from '../composables/dialog'
import { codeLabel, codeLeft, requestCode } from '../composables/codeCooldown'
import { toast } from '../composables/toast'

const itemLink = useItemLink()
const route = useRoute()
const router = useRouter()
const me = computed(() => authState.user)

// v3.2：「我的收藏」「我的对比」搬进「口袋」页；入库日志只有管理员能看
const TABS = computed(() => [
  // [键, 电脑上的名称, 图标, 手机上的短名]
  ['submissions', '我提交的', 'plus', '提交'],
  ...(isAdminUser() ? [['logs', '入库日志', 'clock', '日志']] : []),
  ['comments', '我的评论', 'message', '评论'],
  ['feedback', '我的反馈', 'mail', '反馈'],
  ['settings', '账号设置', 'user', '设置'],
])
const tab = computed(() => (TABS.value.some((t) => t[0] === route.query.tab) ? route.query.tab : 'submissions'))
// 旧链接 /me?tab=favorites|compares 跳到口袋
watch(
  () => route.query.tab,
  (t) => (t === 'favorites' || t === 'compares') && router.replace({ path: '/pocket', query: t === 'compares' ? { tab: 'compares' } : {} }),
  { immediate: true },
)
const stats = ref(null)

// ---- 我提交的 / 我的评论 ----
const subs = ref(null)
const comments = ref(null)

// 我提交的：有条目还在处理 / 审核时每 4 秒自动刷新，状态实时变化
let subsTimer
const ACTIVE = (it) => it.status === 'awaiting' && it.review_state !== 'admin'
async function refreshSubs() {
  clearTimeout(subsTimer)
  try {
    subs.value = await api('/api/me/submissions')
  } catch {
    subs.value ||= { total: 0, items: [] }
  }
  if (tab.value === 'submissions' && subs.value.items.some(ACTIVE)) subsTimer = setTimeout(refreshSubs, 4000)
}
onBeforeUnmount(() => clearTimeout(subsTimer))
const subCounts = computed(() => {
  const c = { reviewing: 0, published: 0, declined: 0 }
  for (const it of subs.value?.items || []) {
    if (it.status === 'awaiting') c.reviewing++
    else if (it.status === 'published') c.published++
    else if (it.status === 'declined') c.declined++
  }
  return c
})

async function loadTab() {
  if (!me.value) return
  if (tab.value === 'submissions') refreshSubs()
  if (tab.value === 'comments' && !comments.value) comments.value = await api('/api/me/comments').catch(() => ({ total: 0, items: [] }))
  if (tab.value === 'settings' && !sessions.value) loadSessions()
}

// ---- v3.3.9 微信绑定 / 解绑、只有微信的账号绑定邮箱（必要时合并）----
const emailValid = (v) => /^[^\s@]+@[^\s@]+\.[A-Za-z]{2,}$/.test(v || '')
function onWechatBound(r) {
  if (r.user) authState.user = r.user
  dlg.value = ''
  toast(r.result?.status === 'merged' ? '已绑定微信，并合并了小程序里的数据' : '已绑定微信', 'success', 3000)
  api('/api/me/stats').then((s) => (stats.value = s)).catch(() => {})
}
async function unbindWechat() {
  if (!(await confirmDialog({ title: '解绑微信？', message: '解绑后不能再用这个微信扫码或在小程序里登录这个账号，可以随时重新绑定。', okText: '解绑' }))) return
  try {
    authState.user = (await api('/api/auth/me/wechat/unbind', { method: 'POST' })).user
    toast('已解绑微信', 'success')
  } catch (e) {
    toast(e.message, 'error')
  }
}
const bindEmail = ref({ email: '', code: '', busy: '' })
const bindLeft = computed(() => codeLeft('login', bindEmail.value.email))
const bindMerge = ref(null) // { ticket, preview }
function openBindEmail() {
  bindEmail.value = { email: '', code: '', busy: '' }
  bindMerge.value = null
  dlg.value = 'email'
}
async function sendBindCode() {
  bindEmail.value.busy = 'send'
  try {
    const r = await requestCode({ purpose: 'login', email: bindEmail.value.email })
    toast(`验证码已发送到 ${bindEmail.value.email}`, 'success')
    if (r.dev_code) toast(`开发环境验证码：${r.dev_code}`, 'info', 8000)
  } catch (e) {
    toast(e.message, 'error')
  } finally {
    bindEmail.value.busy = ''
  }
}
async function submitBindEmail() {
  bindEmail.value.busy = 'save'
  try {
    const r = await api('/api/auth/me/email', { method: 'POST', body: { email: bindEmail.value.email, code: bindEmail.value.code } })
    if (r.status === 'merge') bindMerge.value = r
    else {
      authState.user = r.user
      dlg.value = ''
      toast('已绑定邮箱', 'success')
    }
  } catch (e) {
    toast(e.message, 'error')
  } finally {
    bindEmail.value.busy = ''
  }
}
async function confirmMerge() {
  bindEmail.value.busy = 'merge'
  try {
    const r = await api('/api/auth/me/merge', { method: 'POST', body: { ticket: bindMerge.value.ticket } })
    setSession(r.token, r.user)
    dlg.value = ''
    toast('已合并到邮箱账号', 'success', 3000)
  } catch (e) {
    toast(e.message, 'error')
  } finally {
    bindEmail.value.busy = ''
  }
}

// ---- 资料（v3.2 在弹窗里改：dlg = 'profile' / 'password'）----
const dlg = ref('')
const profile = ref({ nickname: '', avatar: '' })
const savingProfile = ref(false)
watch(me, (u) => u && (profile.value = { nickname: u.nickname, avatar: u.avatar }), { immediate: true })

// 上传头像：服务器裁成正方形、压缩成 WebP 后立即生效
const avatarInput = ref(null)
const uploadingAvatar = ref(false)
async function uploadAvatar(e) {
  const file = e.target.files?.[0]
  e.target.value = ''
  if (!file) return
  uploadingAvatar.value = true
  try {
    const fd = new FormData()
    fd.append('file', file)
    const res = await fetch('/api/auth/me/avatar', { method: 'POST', headers: authHeaders(), body: fd })
    const d = await res.json().catch(() => null)
    if (!res.ok) throw new Error(d?.detail || `上传失败（${res.status}）`)
    authState.user = d.user
    profile.value.avatar = d.user.avatar
    toast(`头像已更新（${Math.max(1, Math.round(d.original_bytes / 1024))}KB 压缩到 ${Math.max(1, Math.round(d.bytes / 1024))}KB）`, 'success', 2500)
  } catch (err) {
    toast(err.message, 'error')
  } finally {
    uploadingAvatar.value = false
  }
}

async function saveProfile() {
  savingProfile.value = true
  try {
    authState.user = (await api('/api/auth/me', { method: 'PATCH', body: profile.value })).user
    toast('资料已保存', 'success')
    dlg.value = ''
  } catch (e) {
    toast(e.message, 'error')
  } finally {
    savingProfile.value = false
  }
}

// ---- 密码 ----
const pw = ref({ old: '', next: '', code: '', useCode: false })
const pwBusy = ref('')
const pwCooldown = computed(() => codeLeft('change'))
const delCooldown = computed(() => codeLeft('delete'))

async function sendCode(purpose) {
  pwBusy.value = 'send'
  try {
    const r = await requestCode({ purpose })
    toast(`验证码已发送到 ${me.value.email}`, 'success')
    if (r.dev_code) toast(`开发环境验证码：${r.dev_code}`, 'info', 8000)
  } catch (e) {
    toast(e.message, 'error')
  } finally {
    pwBusy.value = ''
  }
}

async function savePassword() {
  pwBusy.value = 'save'
  try {
    const body = { new_password: pw.value.next }
    if (me.value.has_password) Object.assign(body, pw.value.useCode ? { code: pw.value.code } : { old_password: pw.value.old })
    await api('/api/auth/password', { method: 'POST', body })
    toast(me.value.has_password ? '密码已修改，其他设备已退出登录' : '密码已设置', 'success', 2500)
    authState.user.has_password = true
    pw.value = { old: '', next: '', code: '', useCode: false }
    dlg.value = ''
    sessions.value = null
    loadSessions()
  } catch (e) {
    toast(e.message, 'error')
  } finally {
    pwBusy.value = ''
  }
}

// ---- 登录设备 ----
const sessions = ref(null)
async function loadSessions() {
  sessions.value = await api('/api/auth/sessions').catch(() => [])
}
async function revoke(s) {
  if (!(await confirmDialog({ title: '让这台设备退出登录？', message: `${s.device} · 最近活跃 ${formatTime(s.last_seen_at)}` }))) return
  await api(`/api/auth/sessions/${s.id}`, { method: 'DELETE' })
  sessions.value = sessions.value.filter((x) => x.id !== s.id)
  toast('已退出该设备', 'success')
}

// ---- 注销 ----
const delCode = ref('')
const delBusy = ref(false)
async function deleteAccount() {
  const ok = await confirmDialog({
    title: '确定注销账号？',
    message: '收藏和收藏分类会被删除且无法恢复；你的评论和提交的条目会保留，显示为「已注销用户」。',
    danger: true,
    okText: '注销账号',
  })
  if (!ok) return
  delBusy.value = true
  try {
    await api('/api/auth/delete', { method: 'POST', body: me.value.email ? { code: delCode.value } : { confirm: delCode.value } })
    clearSession()
    toast('账号已注销', 'success')
    router.replace('/')
  } catch (e) {
    toast(e.message, 'error')
  } finally {
    delBusy.value = false
  }
}

function go(t) {
  router.replace({ query: { tab: t } })
}
// v3.3.15 下划线跟着当前标签的文字滑动（宽度 = 文字宽度）
const tabBar = ref(null)
const tabInk = ref({ opacity: 0 })
function measureTab() {
  nextTick(() => {
    const bar = tabBar.value
    const label = bar?.querySelector('[aria-selected="true"] .tab-label')
    if (!label) return
    const a = bar.getBoundingClientRect()
    const b = label.getBoundingClientRect()
    tabInk.value = { width: `${b.width}px`, transform: `translateX(${b.left - a.left}px)`, opacity: 1 }
  })
}
const tabCount = (k) => (k === 'submissions' ? stats.value?.submissions : k === 'comments' ? stats.value?.comments : 0) || 0
let tabRo
watch(tabBar, (el) => {
  tabRo?.disconnect()
  if (!el) return
  measureTab()
  document.fonts?.ready.then(measureTab)
  tabRo = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(measureTab) : null
  tabRo?.observe(el)
})
watch([tab, stats], measureTab)
onBeforeUnmount(() => tabRo?.disconnect())

watch(tab, loadTab)
watch(me, async (u) => {
  if (!u) return
  stats.value = await api('/api/me/stats').catch(() => null)
  loadTab()
}, { immediate: true })
watch(
  () => authState.ready && !me.value,
  (guest) => guest && requireLogin('登录后查看你的收藏、评论和提交记录'),
  { immediate: true },
)
</script>

<template>
  <div class="mx-auto max-w-5xl">
    <!-- 未登录 -->
    <div v-if="!me" class="panel mx-auto mt-6 flex max-w-md flex-col items-center gap-3 px-6 py-14 text-center">
      <span class="float-y grid h-14 w-14 place-items-center rounded-2xl bg-brand text-white"><Icon name="user" :size="24" /></span>
      <p class="text-lg font-semibold">登录后查看「我的」</p>
      <p class="text-sm text-ink-2">收藏、评论、提交的 Skill、入库进度都在这里</p>
      <button class="btn-primary mt-1" @click="requireLogin()">登录 / 注册</button>
    </div>

    <template v-else>
      <!-- 个人卡片 -->
      <section class="panel relative overflow-hidden p-5 sm:p-7">
        <div class="pointer-events-none absolute -top-24 -right-10 h-60 w-60 rounded-full bg-brand-2/15 blur-3xl" />
        <div class="relative flex flex-wrap items-center gap-4">
          <UserAvatar :user="me" :size="64" class="shadow-[0_10px_24px_-10px_rgb(30_86_214/0.6)]" />
          <div class="min-w-[55%] flex-1">
            <h1 class="flex items-center gap-2 text-[22px] font-extrabold tracking-tight">
              <span class="truncate">{{ me.nickname }}</span>
              <span v-if="me.role === 'admin' || me.role === 'subadmin'" class="tag bg-ok-soft text-ok"><Icon name="shield" :size="12" />{{ me.role === 'admin' ? '超级管理员' : '子管理员' }}</span>
            </h1>
            <!-- v3.3.23 手机上分两行：账号一行、加入时间一行（与小程序一致）；电脑上仍是一行 -->
            <p class="mt-0.5 text-sm text-mute">
              <span class="max-sm:block max-sm:truncate">{{ me.email || (me.username ? '用户名：' + me.username : '微信登录') }}</span><span class="max-sm:hidden"> · </span><span class="max-sm:block">{{ formatTime(me.created_at, false) }} 加入</span>
            </p>
          </div>
          <a v-if="me.role === 'admin' || me.role === 'subadmin'" href="/admin" class="btn-glass btn-sm"><Icon name="layers" :size="15" />管理系统</a>
        </div>
        <div class="relative mt-5 grid grid-cols-3 gap-2.5">
          <button class="stat" @click="router.push('/pocket')"><b>{{ stats?.favorites ?? '—' }}</b><span>收藏</span></button>
          <button class="stat" @click="go('comments')"><b>{{ stats?.comments ?? '—' }}</b><span>评论</span></button>
          <button class="stat" @click="go('submissions')"><b>{{ stats?.submissions ?? '—' }}</b><span>提交的 Skill</span></button>
        </div>
      </section>

      <!-- 标签 -->
      <!-- v3.3.15 下划线标签：手机上平均铺满一行（短名、不带图标、不用横向滚动），电脑上靠左、完整名称带图标 -->
      <div ref="tabBar" class="me-tabs relative mt-6 border-b border-line" role="tablist">
        <div class="flex sm:gap-8">
          <button
            v-for="t in TABS"
            :key="t[0]"
            role="tab"
            :aria-selected="tab === t[0]"
            class="rp flex min-w-0 flex-1 cursor-pointer items-center justify-center gap-1.5 pt-1.5 pb-3 text-[15px] whitespace-nowrap transition-colors duration-300 sm:flex-none sm:justify-start"
            :class="tab === t[0] ? 'font-semibold text-ink' : 'text-mute hover:text-ink-2'"
            @click="go(t[0])"
          >
            <span class="tab-label flex items-center gap-1.5">
              <Icon :name="t[2]" :size="15" class="max-sm:hidden" :class="tab === t[0] ? 'text-brand' : ''" />
              <span class="sm:hidden">{{ t[3] }}</span><span class="max-sm:hidden">{{ t[1] }}</span>
              <span v-if="tabCount(t[0])" class="tab-count" :class="{ on: tab === t[0] }">{{ tabCount(t[0]) }}</span>
            </span>
          </button>
        </div>
        <span class="me-tabs-bar" :style="tabInk" />
      </div>

      <div class="mt-5">
        <!-- 我提交的（v3.2：和收藏一样，手机上一行两张） -->
        <template v-if="tab === 'submissions'">
          <div v-if="!subs" class="grid grid-cols-2 gap-2.5 sm:gap-3.5 lg:grid-cols-3"><div v-for="n in 4" :key="n" class="skeleton-bar h-56 rounded-[12px]" /></div>
          <div v-else-if="!subs.items.length" class="panel flex flex-col items-center gap-3 px-6 py-12 text-center text-sm text-ink-2">
            <Icon name="inbox" :size="34" class="text-mute" />还没有提交过 Skill
            <button class="btn-primary btn-sm" @click="goCollect(router)"><Icon name="plus" :size="15" class="i-plus" />收录</button>
          </div>
          <div v-else class="grid grid-cols-2 gap-2.5 sm:gap-3.5 lg:grid-cols-3">
            <p class="col-span-full -mb-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-ink-2">
              <span>共 {{ subs.total }} 个</span>
              <span v-if="subCounts.reviewing" class="text-sky-600">审核中 {{ subCounts.reviewing }}</span>
              <span class="text-ok">已上线 {{ subCounts.published }}</span>
              <span v-if="subCounts.declined" class="text-danger">未通过 {{ subCounts.declined }}</span>
              <span class="text-xs text-mute">只显示你自己提交的；审核通过后才会公开</span>
              <CompareModeToggle class="ml-auto" />
            </p>
            <ItemCard v-for="(it, i) in subs.items" :key="it.id" :item="it" :index="i" base="/me" show-status dense />
          </div>
        </template>

        <!-- 我的评论 -->
        <template v-else-if="tab === 'comments'">
          <div v-if="!comments" class="space-y-2"><div v-for="n in 3" :key="n" class="skeleton-bar h-20 rounded-2xl" /></div>
          <div v-else-if="!comments.items.length" class="panel px-6 py-12 text-center text-sm text-ink-2">还没有写过使用日志</div>
          <ul v-else class="space-y-2">
            <li v-for="(c, i) in comments.items" :key="c.id" v-reveal="i % 6" class="panel flex gap-3 p-4">
              <UserAvatar :user="me" :size="34" class="shrink-0" />
              <div class="min-w-0 flex-1">
                <div class="flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-xs text-mute">
                  <b class="text-[13.5px] font-semibold text-ink">{{ me.nickname }}</b>
                  <span>评论了</span>
                  <RouterLink :to="itemLink(c.item_id)" class="min-w-0 truncate font-medium text-brand underline underline-offset-4">{{ c.item_name }}</RouterLink>
                  <span v-if="c.input_type === 'voice'" class="tag bg-brand-soft text-brand"><Icon name="mic" :size="12" />语音</span>
                  <span v-if="c.status === 'pending'" class="tag bg-warn-soft text-warn"><Icon name="clock" :size="12" />审核中</span>
                  <time class="ml-auto">{{ formatTime(c.created_at) }}</time>
                </div>
                <p class="mt-1.5 text-[14.5px] leading-relaxed break-words whitespace-pre-wrap">{{ c.content }}</p>
              </div>
            </li>
          </ul>
        </template>

        <!-- 入库日志（只有管理员） -->
        <LogsPanel v-else-if="tab === 'logs'" />

        <!-- 我的反馈 -->
        <MyFeedback v-else-if="tab === 'feedback'" />

        <!-- 账号设置 -->
        <div v-else class="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <!-- v3.2：资料和密码收进弹窗，页面上只放两个入口，敏感信息不直接摊开 -->
          <button v-reveal="0" class="acct-card rp group lg:col-span-1" @click="dlg = 'profile'">
            <UserAvatar :user="me" :size="46" class="shrink-0 transition-transform duration-500 ease-[var(--ease-spring)] group-hover:scale-105" />
            <span class="min-w-0 flex-1 text-left">
              <b class="block text-[15px] font-semibold">修改个人资料</b>
              <span class="mt-0.5 block truncate text-[12.5px] text-mute">昵称、头像</span>
            </span>
            <Icon name="chevron-right" :size="18" class="acct-arrow text-mute" />
          </button>
          <button v-if="me.email || me.username" v-reveal="1" class="acct-card rp group lg:col-span-1" @click="dlg = 'password'">
            <span class="grid h-[46px] w-[46px] shrink-0 place-items-center rounded-2xl bg-brand-soft text-brand transition-transform duration-500 ease-[var(--ease-spring)] group-hover:-rotate-6"><Icon name="lock" :size="20" /></span>
            <span class="min-w-0 flex-1 text-left">
              <b class="block text-[15px] font-semibold">{{ me.has_password ? '修改密码' : '设置密码' }}</b>
              <span class="mt-0.5 block truncate text-[12.5px] text-mute">{{ me.has_password ? '修改后其他设备会退出登录' : '设置后可用邮箱 + 密码登录' }}</span>
            </span>
            <Icon name="chevron-right" :size="18" class="acct-arrow text-mute" />
          </button>
          <!-- v3.3.9 登录方式：微信（绑定 / 解绑）、只有微信的账号补绑邮箱 -->
          <div v-if="me.wechat_bound || meta.data?.wx_qr" v-reveal="2" class="acct-card cursor-default lg:col-span-1">
            <span class="grid h-[46px] w-[46px] shrink-0 place-items-center rounded-2xl" :class="me.wechat_bound ? 'bg-ok-soft text-ok' : 'bg-brand-soft text-brand'"><Icon name="message" :size="20" /></span>
            <span class="min-w-0 flex-1 text-left">
              <b class="block text-[15px] font-semibold">微信</b>
              <span class="mt-0.5 block truncate text-[12.5px] text-mute">{{ me.wechat_bound ? '已绑定，可以用微信扫码或小程序登录' : '绑定后可以用微信扫码登录、在小程序里同步数据' }}</span>
            </span>
            <button v-if="me.wechat_bound" class="btn-ghost btn-sm shrink-0" :disabled="!me.email && !me.username" :title="!me.email && !me.username ? '这个账号只能用微信登录，先绑定邮箱才能解绑' : ''" @click="unbindWechat">解绑</button>
            <button v-else class="btn-primary btn-sm shrink-0" @click="dlg = 'wechat'">绑定微信</button>
          </div>
          <button v-if="!me.email && !me.username" v-reveal="3" class="acct-card rp group lg:col-span-1" @click="openBindEmail">
            <span class="grid h-[46px] w-[46px] shrink-0 place-items-center rounded-2xl bg-warn-soft text-warn"><Icon name="mail" :size="20" /></span>
            <span class="min-w-0 flex-1 text-left">
              <b class="block text-[15px] font-semibold">绑定邮箱</b>
              <span class="mt-0.5 block truncate text-[12.5px] text-mute">绑定后也能用邮箱登录；已有网页账号会合并到一起</span>
            </span>
            <Icon name="chevron-right" :size="18" class="acct-arrow text-mute" />
          </button>
          <MyQuota class="lg:col-span-2" />

          <Teleport to="body">
            <Transition name="sheet">
              <div
                v-if="dlg"
                class="fixed inset-0 z-[72] grid place-items-end bg-ink/25 backdrop-blur-[5px] sm:place-items-center"
                role="dialog"
                aria-modal="true"
                @click.self="dlg = ''"
                @keydown.esc="dlg = ''"
              >
                <div class="sheet-panel glass-strong pb-safe relative max-h-[92vh] w-full overflow-y-auto rounded-t-[14px] shadow-[0_-24px_60px_-24px_rgb(11_47_122/0.45)] sm:max-w-[480px] sm:rounded-[14px]">
                  <div class="px-6 pt-6 pb-6 sm:px-7">
                    <button class="absolute top-4 right-4 grid h-9 w-9 cursor-pointer place-items-center rounded-xl text-mute transition-all duration-300 hover:rotate-90 hover:bg-white/80" aria-label="关闭" @click="dlg = ''">
                      <Icon name="x" :size="18" />
                    </button>
                    <template v-if="dlg === 'profile'">
                      <h2 class="section-title">修改个人资料</h2>
                <label for="me-nick" class="field-label mt-4">昵称</label>
                <input id="me-nick" v-model="profile.nickname" class="field" maxlength="20" />
                <p class="field-label mt-4">头像</p>
                <div class="flex flex-wrap items-center gap-3">
                  <UserAvatar :user="{ nickname: profile.nickname, avatar: profile.avatar }" :size="56" />
                  <button class="btn-glass btn-sm" :disabled="uploadingAvatar" @click="avatarInput.click()">
                    <Icon :name="uploadingAvatar ? 'refresh' : 'image'" :size="15" :class="{ 'animate-spin': uploadingAvatar }" />{{ uploadingAvatar ? '上传中…' : '上传头像' }}
                  </button>
                  <input ref="avatarInput" type="file" accept="image/png,image/jpeg,image/webp,image/gif" class="hidden" @change="uploadAvatar" />
                  <span class="text-xs text-mute">自动裁成正方形并压缩，不超过 10MB</span>
                </div>
                <p class="field-label mt-4">或选一个颜色</p>
                <div class="flex flex-wrap gap-2.5">
                  <button
                    v-for="k in AVATAR_KEYS"
                    :key="k"
                    class="cursor-pointer rounded-full p-0.5 transition-all duration-200"
                    :class="profile.avatar === k ? 'ring-2 ring-brand ring-offset-2' : 'hover:scale-110'"
                    :aria-label="`头像颜色 ${k}`"
                    :aria-pressed="profile.avatar === k"
                    @click="profile.avatar = k"
                  ><UserAvatar :user="{ nickname: profile.nickname, avatar: k }" :size="36" /></button>
                </div>
                <div class="mt-5 flex justify-end">
                  <button class="btn-primary" :disabled="savingProfile || !profile.nickname.trim()" @click="saveProfile">{{ savingProfile ? '保存中…' : '保存资料' }}</button>
                </div>
                    </template>
                    <!-- v3.3.9 绑定微信：网页出小程序码，手机微信扫码确认 -->
                    <template v-else-if="dlg === 'wechat'">
                      <h2 class="section-title">绑定微信</h2>
                      <p class="mt-1.5 mb-5 text-[13px] text-mute">绑定后，在小程序里用这个微信登录，看到的就是这个账号的收藏和对比</p>
                      <WxQrPanel purpose="bind" @done="onWechatBound" />
                    </template>
                    <!-- v3.3.9 绑定邮箱（只有微信的账号）：邮箱已是网页账号时先看合并预览 -->
                    <template v-else-if="dlg === 'email'">
                      <h2 class="section-title">绑定邮箱</h2>
                      <template v-if="!bindMerge">
                        <p class="mt-1.5 text-[13px] text-mute">验证邮箱后，就能用这个邮箱在网页登录</p>
                        <label for="bind-email" class="field-label mt-4">邮箱</label>
                        <div class="flex gap-2">
                          <input id="bind-email" v-model="bindEmail.email" type="email" autocomplete="email" class="field" placeholder="you@example.com" />
                          <button class="btn-glass btn-sm h-11 shrink-0" :disabled="!!bindEmail.busy || bindLeft > 0 || !emailValid(bindEmail.email)" @click="sendBindCode">
                            {{ bindEmail.busy === 'send' ? '发送中…' : bindLeft > 0 ? codeLabel(bindLeft) : '获取验证码' }}
                          </button>
                        </div>
                        <OtpInput v-model="bindEmail.code" class="mt-3" />
                        <div class="mt-5 flex justify-end">
                          <button class="btn-primary" :disabled="bindEmail.code.length !== 6 || !!bindEmail.busy" @click="submitBindEmail">{{ bindEmail.busy === 'save' ? '验证中…' : '绑定' }}</button>
                        </div>
                      </template>
                      <template v-else>
                        <p class="mt-1.5 text-[13px] leading-relaxed text-ink-2">这个邮箱已经是一个网页账号。确认后，当前微信账号会<b class="text-ink">并入</b>那个账号：收藏、评论、对比都会合在一起，之后网页和小程序用的是同一个账号。合并后不能撤销。</p>
                        <div class="mt-4 grid grid-cols-2 gap-2.5 text-[13px]">
                          <div v-for="(side, k) in [['邮箱账号（保留）', bindMerge.preview.primary], ['当前微信账号（并入）', bindMerge.preview.secondary]]" :key="k" class="rounded-xl border border-line bg-white/70 p-3">
                            <p class="text-[12px] text-mute">{{ side[0] }}</p>
                            <p class="mt-1 truncate font-semibold">{{ side[1].nickname }}</p>
                            <p class="mt-1.5 text-[12px] text-ink-2">收藏 {{ side[1].favorites }} · 评论 {{ side[1].comments }} · 对比 {{ side[1].compares }}</p>
                          </div>
                        </div>
                        <div class="mt-5 flex justify-end gap-2">
                          <button class="btn-ghost" @click="bindMerge = null">返回</button>
                          <button class="btn-primary" :disabled="bindEmail.busy === 'merge'" @click="confirmMerge">{{ bindEmail.busy === 'merge' ? '合并中…' : '确认合并' }}</button>
                        </div>
                      </template>
                    </template>
                    <template v-else>
                      <h2 class="section-title">{{ me.has_password ? '修改密码' : '设置密码' }}</h2>
                      <p class="mt-1.5 text-[13px] text-mute">{{ me.has_password ? '修改后其他设备会退出登录' : '设置后可以用「邮箱 + 密码」登录，不必每次收验证码' }}</p>
                <template v-if="me.has_password">
                  <div v-if="me.email" class="mt-3 inline-flex rounded-lg bg-ink/[0.05] p-0.5 text-[13px]">
                    <button class="rounded-md px-3 py-1 cursor-pointer" :class="!pw.useCode ? 'bg-white font-semibold shadow-sm' : 'text-ink-2'" @click="pw.useCode = false">用旧密码</button>
                    <button class="rounded-md px-3 py-1 cursor-pointer" :class="pw.useCode ? 'bg-white font-semibold shadow-sm' : 'text-ink-2'" @click="pw.useCode = true">用邮箱验证码</button>
                  </div>
                  <template v-if="!pw.useCode">
                    <label for="pw-old" class="field-label mt-3">旧密码</label>
                    <input id="pw-old" v-model="pw.old" type="password" autocomplete="current-password" class="field" />
                  </template>
                  <template v-else>
                    <div class="mt-3 flex items-center gap-2">
                      <span class="text-[13px] text-ink-2">发送到 {{ me.email }}</span>
                      <button class="btn-glass btn-sm ml-auto" :disabled="!!pwBusy || pwCooldown > 0" @click="sendCode('change')">
                        {{ pwBusy === 'send' ? '发送中…' : pwCooldown > 0 ? codeLabel(pwCooldown) : '获取验证码' }}
                      </button>
                    </div>
                    <OtpInput v-model="pw.code" class="mt-2" />
                  </template>
                </template>
                <label for="pw-new" class="field-label mt-3">新密码</label>
                <input id="pw-new" v-model="pw.next" type="password" autocomplete="new-password" class="field" placeholder="8 位以上，字母 + 数字" />
                <div class="mt-5 flex justify-end">
                  <button class="btn-primary" :disabled="!!pwBusy || !pw.next || (me.has_password && !(pw.useCode ? pw.code.length === 6 : pw.old))" @click="savePassword">
                    {{ pwBusy === 'save' ? '保存中…' : '保存密码' }}
                  </button>
                </div>
                    </template>
                  </div>
                </div>
              </div>
            </Transition>
          </Teleport>

          <section class="panel p-5 lg:col-span-2">
            <h2 class="section-title">登录设备</h2>
            <ul v-if="sessions" class="mt-3 divide-y divide-line">
              <li v-for="s in sessions" :key="s.id" class="flex items-center gap-3 py-3">
                <span class="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-brand-soft text-brand"><Icon name="cpu" :size="17" /></span>
                <div class="min-w-0 flex-1">
                  <p class="text-[14px] font-medium">{{ s.device }}<span v-if="s.current" class="tag ml-2 bg-ok-soft text-ok">当前设备</span></p>
                  <p class="text-xs text-mute">最近活跃 {{ formatTime(s.last_seen_at) }} · 首次登录 {{ formatTime(s.created_at) }}<template v-if="s.geo"> · {{ s.geo }}</template></p>
                </div>
                <button v-if="!s.current" class="btn-ghost btn-sm text-danger" @click="revoke(s)">退出</button>
              </li>
            </ul>
            <div v-else class="mt-3 space-y-2"><div v-for="n in 2" :key="n" class="skeleton-bar h-12 rounded-xl" /></div>
          </section>

          <section v-if="me.role !== 'admin' && me.role !== 'subadmin'" class="panel border-danger/20 p-5 lg:col-span-2">
            <h2 class="section-title text-danger">注销账号</h2>
            <p class="mt-1.5 text-[13px] leading-relaxed text-ink-2">收藏和收藏分类会被删除；评论和提交的条目保留，显示为「已注销用户」。{{ me.email ? '需要邮箱验证码确认。' : '' }}</p>
            <div class="mt-3 flex flex-wrap items-center gap-2">
              <template v-if="me.email">
                <button class="btn-glass btn-sm" :disabled="!!pwBusy || delCooldown > 0" @click="sendCode('delete')">{{ pwBusy === 'send' ? '发送中…' : delCooldown > 0 ? codeLabel(delCooldown) : '获取验证码' }}</button>
                <OtpInput v-model="delCode" class="w-full sm:w-72" />
                <button class="btn-danger btn-sm" :disabled="delCode.length !== 6 || delBusy" @click="deleteAccount">注销账号</button>
              </template>
              <!-- v3.3.17 只有微信的账号没有邮箱：输入「注销」确认 -->
              <template v-else>
                <input v-model="delCode" class="field w-full sm:w-56" placeholder="输入「注销」确认" autocomplete="off" />
                <button class="btn-danger btn-sm" :disabled="delCode.trim() !== '注销' || delBusy" @click="deleteAccount">注销账号</button>
              </template>
            </div>
          </section>
        </div>
      </div>
    </template>

    <RouterView v-slot="{ Component }">
      <Transition name="sheet">
        <component :is="Component" v-if="Component" />
      </Transition>
    </RouterView>
  </div>
</template>

<style scoped>
/* v3.3.15 「我的」下划线标签 */
.me-tabs-bar {
  position: absolute;
  left: 0;
  bottom: -1px;
  height: 2.5px;
  border-radius: 2px;
  background: var(--color-brand);
  transition: transform 0.45s var(--ease-spring), width 0.4s var(--ease-out-expo), opacity 0.2s;
}
.tab-count {
  min-width: 18px;
  padding: 0 5px;
  border-radius: 999px;
  background: var(--color-hover);
  color: var(--color-mute);
  font-size: 11px;
  font-weight: 600;
  line-height: 17px;
  text-align: center;
  font-variant-numeric: tabular-nums;
  transition: background-color 0.3s, color 0.3s;
}
.tab-count.on {
  background: var(--color-brand-soft);
  color: var(--color-brand);
}
.stat {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  padding: 12px 14px;
  border-radius: 16px;
  background: rgb(255 255 255 / 0.6);
  border: 1px solid var(--color-edge);
  cursor: pointer;
  transition: transform 0.3s, background-color 0.3s;
  text-align: left;
}
.stat:hover {
  transform: translateY(-2px);
  background: rgb(255 255 255 / 0.85);
}
.stat b {
  font-size: 22px;
  font-weight: 800;
  font-variant-numeric: tabular-nums;
  background: linear-gradient(135deg, var(--color-brand), var(--color-brand-2));
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
.stat span {
  font-size: 12.5px;
  color: var(--color-mute);
}
.acct-card {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 16px 18px;
  border-radius: 14px;
  border: 1px solid var(--color-line);
  background: var(--color-panel, #fff);
  cursor: pointer;
  transition: transform 0.35s var(--ease-out-expo), border-color 0.3s, box-shadow 0.45s var(--ease-out-expo);
}
.acct-card:hover {
  transform: translateY(-2px);
  border-color: #b9cbea;
  box-shadow: 0 18px 34px -24px rgb(11 47 122 / 0.6);
}
.acct-card:active {
  transform: scale(0.99);
}
.acct-arrow {
  transition: transform 0.4s var(--ease-spring), color 0.3s;
}
.acct-card:hover .acct-arrow {
  transform: translateX(3px);
  color: var(--color-brand);
}
</style>
