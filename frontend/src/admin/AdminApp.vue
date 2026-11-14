<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, RouterView, useRoute } from 'vue-router'
import { api } from '../api'
import Icon from '../components/Icon.vue'
import UserAvatar from '../components/UserAvatar.vue'
import { authState, clearSession, initAuth, logout } from '../composables/auth'
import AdminLogin from './components/AdminLogin.vue'
import AdminSetup from './components/AdminSetup.vue'
import AdminSearch from './components/AdminSearch.vue'
import ADialog from './components/ADialog.vue'
import AChoiceDialog from './components/AChoiceDialog.vue'
import AVerifyDialog from './components/AVerifyDialog.vue'
import AReasonDialog from './components/AReasonDialog.vue'
import AToasts from './components/AToasts.vue'
import ATaskTray from './components/ATaskTray.vue'
import { can, ROLE_LABEL } from './composables/usePermissions'
import { MODULES } from './modules'

const route = useRoute()
const summary = ref({})
const navOpen = ref(false)
const menuOpen = ref(false)

// 所有管理员角色（超级管理员、内容审核、客服、只读，以及旧的子管理员）都能进入管理端，能看哪些模块由权限决定
const isAdmin = computed(() => !!ROLE_LABEL[authState.user?.role])
const roleLabel = computed(() => ROLE_LABEL[authState.user?.role] || '管理员')
// 接口返回 401 时 api() 会打开登录（authState.modal），这里统一显示管理端自己的登录页
const needLogin = computed(() => authState.ready && (!authState.user || authState.modal.open))
const current = computed(() => route.meta.module || MODULES[0])
const groups = computed(() => {
  const out = []
  for (const m of MODULES.filter((x) => can(x.key))) {
    const g = out.find((x) => x.name === m.group)
    if (g) g.items.push(m)
    else out.push({ name: m.group, items: [m] })
  }
  return out
})

async function loadSummary() {
  if (!isAdmin.value || authState.user?.needs_setup || document.hidden) return
  try {
    summary.value = await api('/api/admin/summary')
  } catch {}
}

async function signOut() {
  menuOpen.value = false
  await logout()
}

function switchAccount() {
  clearSession()
}

let timer
onMounted(async () => {
  await initAuth()
  timer = setInterval(loadSummary, 30000)
})
onBeforeUnmount(() => clearInterval(timer))
// 登录成为管理员时取一次角标；之后切换页面（不含只改 query）和每 30 秒刷新
watch(isAdmin, (v) => v && loadSummary(), { immediate: true })
// 侧栏选中底块：跟着当前模块滑过去
const navBox = ref(null)
const navThumb = ref({ opacity: 0 })
function measureNav() {
  const a = navBox.value?.querySelector('[aria-current="page"]')
  navThumb.value = a ? { transform: `translateY(${a.offsetTop}px)`, height: `${a.offsetHeight}px`, opacity: 1 } : { opacity: 0 }
}
watch([() => route.path, isAdmin, () => authState.ready, needLogin], () => nextTick(measureNav))
watch(() => route.path, (p, old) => {
  navOpen.value = false
  if (old) loadSummary()
  document.title = `${current.value.label} · Skill Pocket 管理端`
}, { immediate: true })
</script>

<template>
  <div v-if="!authState.ready" class="grid min-h-dvh place-items-center text-mute">加载中…</div>

  <AdminLogin v-else-if="needLogin" />

  <AdminSetup v-else-if="authState.user.needs_setup" />

  <div v-else-if="!isAdmin" class="grid min-h-dvh place-items-center px-4">
    <div class="card w-full max-w-sm p-8 text-center">
      <span class="mx-auto grid h-12 w-12 place-items-center rounded-full bg-warn-soft text-warn"><Icon name="lock" :size="22" /></span>
      <h1 class="mt-4 mb-1 text-lg font-semibold">没有管理员权限</h1>
      <p class="text-sm text-ink-2">当前登录的是 {{ authState.user.email || authState.user.nickname }}，管理端只对管理员账号开放。</p>
      <div class="mt-6 flex justify-center gap-2">
        <a href="/" class="btn">返回主站</a>
        <button class="btn btn-primary" @click="switchAccount">换个账号登录</button>
      </div>
    </div>
  </div>

  <div v-else class="min-h-dvh lg:grid lg:grid-cols-[224px_1fr]">
    <!-- 侧栏：桌面固定，窄屏抽屉 -->
    <Transition name="fade">
      <div v-if="navOpen" class="fixed inset-0 z-30 bg-ink/30 lg:hidden" @click="navOpen = false" />
    </Transition>
    <aside
      class="fixed inset-y-0 left-0 z-40 flex w-[224px] flex-col border-r border-line bg-white px-3 py-4 transition-transform duration-200 lg:sticky lg:top-0 lg:h-dvh lg:translate-x-0"
      :class="navOpen ? 'translate-x-0' : '-translate-x-full'"
    >
      <RouterLink to="/" class="flex items-center gap-2.5 px-2 pb-4">
        <i class="logo-mark" aria-hidden="true"><b /><b /><b /><b /></i>
        <span class="leading-tight"><b class="block text-[15px]">Skill Pocket</b><span class="text-[11.5px] text-mute">管理端</span></span>
      </RouterLink>
      <nav class="-mr-3 flex-1 overflow-y-auto pr-3" aria-label="管理模块">
        <div ref="navBox" class="relative">
        <span class="nav-thumb pointer-events-none absolute inset-x-0 top-0 rounded-[7px] bg-primary-soft" :style="navThumb" />
        <template v-for="(g, gi) in groups" :key="g.name">
          <p class="cap px-2.5 pt-3 pb-1" :class="{ 'pt-1': gi === 0 }">{{ g.name }}</p>
          <RouterLink
            v-for="m in g.items"
            :key="m.key"
            :to="m.path"
            class="nav-link relative z-[1] mb-0.5 flex h-[38px] items-center gap-2.5 rounded-[7px] px-2.5 text-ink-2 hover:text-ink"
            :class="{ 'font-semibold !text-primary': current.key === m.key }"
            :aria-current="current.key === m.key ? 'page' : undefined"
          >
            <Icon :name="m.icon" :size="17" />{{ m.label }}
            <span
              v-if="m.badge && m.badge(summary)"
              class="grid h-5 min-w-5 place-items-center rounded-full px-1.5 text-[11px] font-semibold text-white"
              :class="['ml-auto', m.urgent && m.urgent(summary) ? 'bg-bad' : 'bg-primary']"
            >{{ m.badge(summary) > 99 ? '99+' : m.badge(summary) }}</span>
          </RouterLink>
        </template>
        </div>
      </nav>
      <a href="/" class="mt-2 flex h-9 items-center gap-2 rounded-lg px-2.5 text-[13px] text-mute hover:bg-[#f1f5fb] hover:text-ink">
        <Icon name="arrow-left" :size="15" />返回主站
      </a>
    </aside>

    <main class="min-w-0">
      <header class="sticky top-0 z-20 flex h-[60px] items-center gap-3 border-b border-line bg-white px-4 lg:px-6">
        <button class="btn h-9 w-9 px-0 lg:hidden" aria-label="打开导航" @click="navOpen = true"><Icon name="menu" :size="18" /></button>
        <p class="min-w-0 truncate text-mute"><span class="hidden sm:inline">管理端 / {{ current.group }} / </span><b class="font-semibold text-ink">{{ current.label }}</b></p>
        <div class="ml-auto flex items-center gap-2"><AdminSearch />
        <div class="relative">
          <button class="flex items-center gap-2 rounded-lg px-1.5 py-1 hover:bg-[#f1f5fb]" :aria-expanded="menuOpen" @click="menuOpen = !menuOpen">
            <UserAvatar :user="authState.user" :size="32" />
            <span class="hidden text-left leading-tight sm:block"><b class="block text-[13px] font-semibold">{{ authState.user.nickname }}</b><span class="text-[11.5px] text-mute">{{ roleLabel }}</span></span>
            <Icon name="chevron-down" :size="15" class="text-mute" />
          </button>
          <Transition name="fade">
            <div v-if="menuOpen" class="absolute top-full right-0 z-30 mt-1.5 w-56 rounded-lg border border-line bg-white py-1.5 shadow-[0_8px_24px_-8px_rgba(15,29,51,.18)]">
              <p class="truncate px-3.5 py-1.5 text-xs text-mute">{{ authState.user.email || 'admin' }} · {{ roleLabel }}</p>
              <a href="/me" class="flex h-9 items-center gap-2 px-3.5 text-[13px] hover:bg-[#f1f5fb]"><Icon name="user" :size="15" />我的账号（主站）</a>
              <button class="flex h-9 w-full items-center gap-2 px-3.5 text-left text-[13px] text-bad hover:bg-bad-soft" @click="signOut"><Icon name="log-out" :size="15" />退出登录</button>
            </div>
          </Transition>
          <div v-if="menuOpen" class="fixed inset-0 z-20" @click="menuOpen = false" />
        </div>
        </div>
      </header>
      <div class="mx-auto max-w-[1360px] px-4 py-5 lg:px-6 lg:py-6">
        <p v-if="can(current.key) && !can(current.key, 'w')" class="mb-4 flex items-center gap-2 rounded-lg bg-subtle px-3.5 py-2 text-[13px] text-ink-2"><Icon name="lock" :size="14" />当前角色（{{ roleLabel }}）对「{{ current.label }}」只有查看权限</p>
        <div v-if="!can(current.key)" class="card mx-auto mt-10 max-w-md p-8 text-center">
          <span class="mx-auto grid h-12 w-12 place-items-center rounded-full bg-warn-soft text-warn"><Icon name="lock" :size="22" /></span>
          <h2 class="mt-4 mb-1 text-lg font-semibold">没有权限</h2>
          <p class="m-0 text-sm text-ink-2">当前角色（{{ roleLabel }}）不能访问「{{ current.label }}」</p>
          <RouterLink to="/" class="btn mt-5">回到概览</RouterLink>
        </div>
        <RouterView v-else v-slot="{ Component }">
          <component :is="Component" :summary="summary" @changed="loadSummary" />
        </RouterView>
      </div>
    </main>
  </div>

  <ADialog />
  <AReasonDialog />
  <AChoiceDialog />
  <AVerifyDialog />
  <AToasts />
  <ATaskTray v-if="isAdmin && !needLogin && !authState.user?.needs_setup" />
</template>

<style scoped>
.logo-mark { width: 26px; height: 26px; display: grid; grid-template-columns: 1fr 1fr; gap: 2px; padding: 5px; background: var(--color-primary); border-radius: 7px; transition: transform .6s var(--ease-spring); }
.logo-mark b { background: #fff; border-radius: 1px; }
.logo-mark b:nth-child(2), .logo-mark b:nth-child(3) { opacity: .55; }
a:hover > .logo-mark { transform: rotate(90deg); }
.nav-thumb { transition: transform .5s var(--ease-spring), height .4s var(--ease-out-expo), opacity .3s; }
.nav-thumb::before { content: ''; position: absolute; left: 0; top: 9px; bottom: 9px; width: 2px; border-radius: 2px; background: var(--color-primary); }
.nav-link { transition: color .25s, padding .35s var(--ease-out-expo); }
.nav-link:hover:not([aria-current]) { padding-left: 14px; }
</style>
