<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'
import AppDialog from './components/AppDialog.vue'
import QuotaDialog from './components/QuotaDialog.vue'
import TaskTray from './components/TaskTray.vue'
import ChangelogPanel from './components/ChangelogPanel.vue'
import Icon from './components/Icon.vue'
import LoginModal from './components/LoginModal.vue'
import MiniProgramQr from './components/MiniProgramQr.vue'
import ModeSwitch from './components/ModeSwitch.vue'
import { homeMode } from './composables/homeMode'
import PrivacyNotice from './components/PrivacyNotice.vue'
import CompareTray from './components/CompareTray.vue'
import FeedbackModal from './components/FeedbackModal.vue'
import OnboardingTour from './components/OnboardingTour.vue'
import NotificationBell from './components/NotificationBell.vue'
import UserMenu from './components/UserMenu.vue'
import { toasts } from './composables/toast'
import { authState } from './composables/auth'
import { favState } from './composables/favorites'
import { loadMeta, meta } from './composables/meta'
import { bumpTasks } from './composables/tasks'
import { goCollect, goSiteSearch, homeSignal } from './composables/collect'

const route = useRoute()
const router = useRouter()
const scrolled = ref(false)
const progress = ref(0)

const isHome = (p) => p === '/' || /^\/items\/\d+$/.test(p)
// v3.2 顶栏：主页 / 榜单 / 口袋（我的收藏 + 我的 AI 对比）/ 我的；手机底栏同样四项，中间是加号
const mpOpen = ref(false)
// 私有化部署：public/mp-qrcode.jpg 存在才显示「小程序」入口
const hasMp = ref(false)
const mpProbe = new Image()
mpProbe.onload = () => (hasMp.value = true)
mpProbe.src = '/mp-qrcode.jpg'
const siteHost = location.host
const frameHome = ref(null)
const NAV = [
  { to: '/', label: '主页', icon: 'home', match: isHome },
  { to: '/rankings', label: '榜单', icon: 'trend', match: (p) => p.startsWith('/rankings') },
  { to: '/pocket', label: '口袋', icon: 'pocket', match: (p) => p.startsWith('/pocket') || p.startsWith('/compare') },
  { to: '/me', label: '我的', icon: 'user', match: (p) => p.startsWith('/me') },
]
const TABS = [NAV[0], NAV[1], { add: true }, NAV[2], NAV[3]]
const activeTab = computed(() => TABS.findIndex((t) => !t.add && t.match(route.path)))

// v3.2 手机底栏加号：弹出「本站搜索 / GitHub AI 搜索」两个气泡
const addOpen = ref(false)
function pickAdd(kind) {
  addOpen.value = false
  if (kind === 'github') goCollect(router)
  else if (kind === 'image') router.push('/').then(() => homeSignal.simpleImage++) // v3.3.96 简洁模式：扫描识别图片
  else goSiteSearch(router)
}
const simpleHome = computed(() => homeMode.value === 'simple')
watch(() => route.fullPath, () => (addOpen.value = false))

// 顶栏导航：下划线跟着悬停的链接滑动，离开后回到当前页
const nav = ref(null)
const ink = ref({ opacity: 0 })
function inkTo(el) {
  ink.value = el ? { width: `${el.offsetWidth - 20}px`, transform: `translateX(${el.offsetLeft + 10}px)`, opacity: 1 } : { opacity: 0 }
}
const inkHome = () => inkTo(nav.value?.querySelector('[aria-current="page"]'))
watch(() => route.path, () => nextTick(inkHome))

// 抽屉开关不应触发整页切换动画，所以 key 只取顶层路由
const pageKey = (r) => r.matched[0]?.path ?? r.path

function onScroll() {
  const h = document.documentElement.scrollHeight - innerHeight
  scrolled.value = scrollY > 8
  progress.value = h > 0 ? scrollY / h : 0
}

onMounted(() => {
  addEventListener('scroll', onScroll, { passive: true })
  addEventListener('resize', inkHome)
  nextTick(inkHome)
  document.fonts?.ready.then(inkHome)
})
// 换了账号：收藏状态缓存作废，收藏数重新取
watch(
  () => authState.version,
  async () => {
    favState.map = {}
    bumpTasks()
    favState.count = (await loadMeta(true))?.favorites ?? null
  },
)
onBeforeUnmount(() => {
  removeEventListener('scroll', onScroll)
  removeEventListener('resize', inkHome)
})
</script>

<template>
  <div class="scroll-progress" :style="{ transform: `scaleX(${progress})` }" aria-hidden="true" />

  <header
    class="sticky top-0 z-30 border-b border-line bg-white/82 backdrop-blur-[14px] backdrop-saturate-[1.4] transition-shadow duration-400"
    :class="{ 'shadow-[0_8px_24px_-20px_rgb(11_47_122/0.45)]': scrolled }"
  >
    <div class="mx-auto flex h-14 max-w-[1440px] items-center gap-2.5 px-4 md:px-6">
      <RouterLink to="/" class="logo-mark flex shrink-0 cursor-pointer items-center gap-2 text-[15px] font-semibold tracking-[-0.01em] whitespace-nowrap" title="Skill Pocket · 你的 Skill 口袋">
        <i aria-hidden="true"><b /><b /><b /><b /></i>Skill Pocket
      </RouterLink>
      <nav ref="nav" class="relative ml-3.5 hidden gap-0.5 md:flex" aria-label="主导航" @mouseleave="inkHome">
        <RouterLink
          v-for="n in NAV"
          :key="n.to"
          :to="n.to"
          class="relative z-[1] px-2.5 py-1.5 text-[13px] leading-5 transition-colors duration-300 hover:text-brand"
          :class="n.match(route.path) ? 'text-brand' : 'text-ink-2'"
          :aria-current="n.match(route.path) ? 'page' : undefined"
          @mouseenter="inkTo($event.currentTarget)"
        >{{ n.label }}</RouterLink>
        <!-- v3.3.30 小程序：点开弹出小程序码（只在电脑顶栏） -->
        <button
          v-if="hasMp"
          class="relative z-[1] cursor-pointer px-2.5 py-1.5 text-[13px] leading-5 transition-colors duration-300 hover:text-brand"
          :class="mpOpen ? 'text-brand' : 'text-ink-2'"
          @mouseenter="inkTo($event.currentTarget)"
          @click="mpOpen = true"
        >小程序</button>
        <span class="absolute -bottom-[11px] left-0 h-0.5 rounded-sm bg-brand transition-[transform,width,opacity] duration-450 ease-out-expo" :style="ink" />
      </nav>
      <div class="flex-1" />
      <!-- v3.3.96 首页模式开关（只在主页显示，和小程序一样放在铃铛旁） -->
      <ModeSwitch v-if="isHome(route.path)" class="mr-0.5" />
      <!-- 手机主页上顶栏放了模式开关，更新日志收起（在「我的」里仍能看到） -->
      <span class="contents" :class="{ 'max-sm:hidden': isHome(route.path) }"><ChangelogPanel /></span>
      <NotificationBell />
      <UserMenu />
    </div>
  </header>

  <!-- 首页自己铺满（页头背景通栏），其余页面放在居中的版心里。
       版心样式跟着「正在显示的页面」走（放在过渡元素里），切页时旧页面淡出期间不会突然失去版心、跳到左上角 -->
  <main>
    <!-- v3.3.33 首页用 KeepAlive 缓存（GitHub 检索过程和结果切页面也保留）。版心样式放在外层，
         在新页面进场前（旧页面淡出后）才切换，切页时旧页面不会突然失去版心 -->
    <div :class="(frameHome ?? isHome(route.path)) ? 'pb-10' : 'mx-auto max-w-[1280px] px-4 pt-5 pb-16 md:px-6 md:pt-7'">
      <RouterView v-slot="{ Component, route: r }">
        <Transition name="page" mode="out-in" @before-enter="frameHome = isHome(route.path)">
          <KeepAlive include="HomeView">
            <component :is="Component" :key="pageKey(r)" />
          </KeepAlive>
        </Transition>
      </RouterView>
    </div>
  </main>

  <footer class="border-t border-line bg-panel">
    <div class="mx-auto flex max-w-[1440px] flex-wrap gap-x-7 gap-y-3 px-4 pt-6 pb-32 text-xs leading-5 text-mute md:px-6 md:pb-10">
      <RouterLink to="/terms" class="foot-link">用户协议</RouterLink>
      <RouterLink to="/privacy" class="foot-link">隐私政策</RouterLink>
      <RouterLink to="/rankings" class="foot-link">榜单</RouterLink>
      <a v-if="meta.data?.contact_email" :href="`mailto:${meta.data.contact_email}`" class="foot-link">联系站长：{{ meta.data.contact_email }}</a>
      <span class="font-mono text-[11px] md:ml-auto">Skill Pocket · {{ siteHost }}</span>
    </div>
  </footer>

  <!-- 加号气泡：背景压暗，两个选项从加号处弹起（错开出现） -->
  <Transition name="fab">
    <div v-if="addOpen" class="fab-layer fixed inset-0 z-[29] md:hidden" @click="addOpen = false">
      <div class="fab-dim absolute inset-0 bg-[rgb(11_31_68/0.28)] backdrop-blur-[2px]" />
      <!-- v3.3.96 简洁模式：只有一项「扫描识别图片」 -->
      <div v-if="simpleHome" class="absolute inset-x-0 bottom-[calc(76px+env(safe-area-inset-bottom))] flex justify-center px-6" @click.stop>
        <button class="fab-bubble fab-ai rp flex w-[180px] cursor-pointer flex-col items-start gap-2 rounded-2xl p-3.5 text-left text-white" style="--d: 0ms; --x: 0px" @click="pickAdd('image')">
          <span class="grid h-10 w-10 place-items-center rounded-xl bg-white/16"><Icon name="image" :size="20" /></span>
          <b class="text-[14px] font-semibold">扫描识别图片</b>
        </button>
      </div>
      <div v-else class="absolute inset-x-0 bottom-[calc(76px+env(safe-area-inset-bottom))] flex justify-center gap-3 px-6" @click.stop>
        <button class="fab-bubble rp flex w-[150px] cursor-pointer flex-col items-start gap-2 rounded-2xl border border-line bg-white p-3.5 text-left shadow-[0_18px_36px_-16px_rgb(11_47_122/0.55)]" style="--d: 0ms; --x: 20px" @click="pickAdd('site')">
          <span class="grid h-10 w-10 place-items-center rounded-xl bg-brand-soft text-brand"><Icon name="grid" :size="20" /></span>
          <b class="text-[14px] font-semibold">本站搜索</b>
        </button>
        <button class="fab-bubble fab-ai rp flex w-[150px] cursor-pointer flex-col items-start gap-2 rounded-2xl p-3.5 text-left text-white" style="--d: 60ms; --x: -20px" @click="pickAdd('github')">
          <span class="relative grid h-10 w-10 place-items-center rounded-xl bg-white/16">
            <Icon name="github" :size="20" />
            <span class="fab-ai-badge absolute -top-1.5 -right-2 rounded-full bg-white px-1.5 font-mono text-[10px] leading-4 font-extrabold text-brand">AI</span>
          </span>
          <b class="text-[14px] font-semibold">GitHub AI 搜索</b>
        </button>
      </div>
    </div>
  </Transition>

  <!-- 手机底部导航：选中胶囊跟着滑动，中间是加号 -->
  <nav class="pb-safe fixed inset-x-0 bottom-0 z-30 border-t border-line bg-white/90 backdrop-blur-[16px] md:hidden" aria-label="主导航">
    <div class="relative grid h-[60px] grid-cols-5">
      <span
        class="pointer-events-none absolute top-1.5 left-0 flex h-[30px] w-1/5 justify-center transition-[transform,opacity] duration-500 ease-[var(--ease-spring)]"
        :style="{ transform: `translateX(${Math.max(activeTab, 0) * 100}%)`, opacity: activeTab < 0 ? 0 : 1 }"
      ><span class="h-[30px] w-[52px] rounded-full bg-brand-soft" /></span>
      <template v-for="t in TABS" :key="t.to || 'add'">
        <button v-if="t.add" class="tab-add relative z-[1] grid cursor-pointer place-items-center" :class="{ open: addOpen }" aria-label="搜索" :aria-expanded="addOpen" @click="addOpen = !addOpen">
          <span class="grid h-10 w-10 place-items-center rounded-xl bg-brand text-white shadow-[0_10px_20px_-10px_rgb(30_86_214/0.8)]"><Icon name="plus" :size="20" /></span>
        </button>
        <RouterLink
          v-else
          :to="t.to"
          class="relative z-[1] flex cursor-pointer flex-col items-center justify-center gap-[3px] text-[10.5px] transition-colors duration-300"
          :class="t.match(route.path) ? 'font-medium text-brand' : 'text-mute'"
          :aria-current="t.match(route.path) ? 'page' : undefined"
        >
          <Icon :name="t.icon" :size="21" class="transition-transform duration-400 ease-[var(--ease-spring)]" :class="{ '-translate-y-px scale-108': t.match(route.path) }" />
          <span>{{ t.label }}</span>
        </RouterLink>
      </template>
    </div>
  </nav>

  <!-- v3.3.28 去掉「回到顶部」按钮：会挡住手机底部的任务 / 对比小圆按钮 -->

  <MiniProgramQr v-model="mpOpen" />
  <LoginModal />
  <FeedbackModal />
  <OnboardingTour />

  <AppDialog />
  <QuotaDialog />
  <CompareTray />
  <PrivacyNotice />
  <TaskTray />

  <div class="pointer-events-none fixed inset-x-0 bottom-[calc(84px+env(safe-area-inset-bottom))] z-[95] flex flex-col items-center gap-2 px-4 md:bottom-8" aria-live="polite">
    <TransitionGroup name="toast">
      <div
        v-for="t in toasts"
        :key="t.id"
        class="flex items-center gap-2 rounded-full px-3.5 py-2 text-[13px] leading-5 text-white shadow-[0_14px_30px_-14px_rgb(11_47_122/0.7)]"
        :class="t.type === 'error' ? 'bg-danger' : 'bg-ink'"
      >
        <Icon :name="t.type === 'error' ? 'alert' : 'check'" :size="15" :class="t.type === 'error' ? '' : 'text-sky'" />{{ t.message }}
      </div>
    </TransitionGroup>
  </div>
</template>

<style scoped>
.logo-mark i {
  width: 22px;
  height: 22px;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 2px;
  padding: 4px;
  background: var(--color-brand);
  border-radius: 6px;
  transition: transform 0.6s var(--ease-spring);
}
.logo-mark i b {
  background: #fff;
  border-radius: 1px;
  transition: opacity 0.4s var(--ease-out-expo), transform 0.5s var(--ease-spring);
}
.logo-mark i b:nth-child(2),
.logo-mark i b:nth-child(3) {
  opacity: 0.55;
}
.logo-mark:hover i {
  transform: rotate(90deg);
}
.logo-mark:hover i b:nth-child(1),
.logo-mark:hover i b:nth-child(4) {
  opacity: 0.55;
  transform: scale(0.8);
}
.logo-mark:hover i b:nth-child(2),
.logo-mark:hover i b:nth-child(3) {
  opacity: 1;
}
.foot-link {
  background: linear-gradient(var(--color-brand), var(--color-brand)) 0 100% / 0 1px no-repeat;
  transition: background-size 0.4s var(--ease-out-expo), color 0.3s;
}
.foot-link:hover {
  color: var(--color-brand);
  background-size: 100% 1px;
}
.tab-add:active > span {
  transform: rotate(45deg) scale(0.9);
  border-radius: 50%;
}
.tab-add > span {
  transition: transform 0.45s var(--ease-spring), border-radius 0.45s var(--ease-out-expo);
}
/* v3.2 加号展开时转成 ×，变圆 */
.tab-add.open > span {
  transform: rotate(135deg);
  border-radius: 50%;
}
.fab-bubble {
  transition: transform 0.5s var(--ease-spring) var(--d), opacity 0.3s var(--ease-out-expo) var(--d);
}
.fab-bubble:active {
  transform: scale(0.96);
}
.fab-ai {
  background: linear-gradient(135deg, var(--color-brand-ink, #0b2f7a), var(--color-brand) 55%, var(--color-sky));
  box-shadow: 0 18px 36px -14px rgb(30 86 214 / 0.85), 0 0 0 1px rgb(255 255 255 / 0.12) inset;
}
.fab-ai-badge {
  box-shadow: 0 0 0 0 rgb(255 255 255 / 0.7);
  animation: aiglow 2.2s ease-in-out infinite;
}
@keyframes aiglow {
  50% {
    box-shadow: 0 0 10px 3px rgb(160 205 255 / 0.95);
  }
}
.fab-dim {
  transition: opacity 0.3s;
}
.fab-enter-from .fab-dim,
.fab-leave-to .fab-dim {
  opacity: 0;
}
.fab-enter-from .fab-bubble,
.fab-leave-to .fab-bubble {
  opacity: 0;
  transform: translate(var(--x), 46px) scale(0.6);
}
.fab-enter-active,
.fab-leave-active {
  transition: opacity 0.55s;
}
.fab-leave-active .fab-bubble {
  transition-delay: 0ms;
  transition-duration: 0.25s;
}
@media (prefers-reduced-motion: reduce) {
  .fab-ai-badge {
    animation: none;
  }
}
</style>
