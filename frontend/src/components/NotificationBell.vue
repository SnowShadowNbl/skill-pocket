<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { timeAgo } from '../api'
import { authState } from '../composables/auth'
import { goSubscribe, loadNotes, loadSubs, markAllNotesRead, markNoteRead, noteState, toggleSub } from '../composables/notifications'
import Icon from './Icon.vue'

// v3.3 右上角铃铛：订阅分类的上新、收藏仓库的新版本；每 5 分钟刷新一次提醒点。
// v3.3.20 打开不再全部标已读：点哪条只去掉哪条的提醒点，标题栏有「全部已读」。
// 手机上面板最多占半屏，消息列表在面板里滚动（不带动页面）；手指碰到面板以外就收起。
const router = useRouter()
const open = ref(false)
const root = ref(null)
const panel = ref(null)
// v3.3.21 手机上把遮罩和面板挂到 body：顶栏有毛玻璃（backdrop-filter），会让里面的 fixed 元素只相对顶栏定位，
// 遮罩就只盖住顶栏那一条，手指在下面滑动时摸到的是页面本身。挂到 body 后才真正盖住整个屏幕。
const mq = typeof matchMedia === 'function' ? matchMedia('(max-width: 639.98px)') : null
const phone = ref(!!mq?.matches)
const onMq = (e) => (phone.value = e.matches)
// 遮罩比面板多留一会儿：面板一碰就收起，遮罩等这次触摸结束（抬手的点击）再撤，免得点击落到下面的铃铛或卡片上
const shield = ref(false)
let shieldTimer
watch(open, (on) => {
  clearTimeout(shieldTimer)
  if (on) shield.value = true
  else shieldTimer = setTimeout(() => (shield.value = false), 450) // 不管怎么关的，遮罩都随后撤掉
})
function dismiss() {
  open.value = false
}
let timer

function toggle() {
  open.value = !open.value
  if (open.value) loadNotes()
}
function go(n) {
  markNoteRead(n)
  open.value = false
  if (n.link) router.push(n.link)
}
function subscribeMore() {
  open.value = false
  goSubscribe(router)
}
function openSub(s) {
  open.value = false
  router.push({ path: '/', query: { category: s.code, sort: 'collected' } })
}
function onDoc(e) {
  if (!open.value || root.value?.contains(e.target) || panel.value?.contains(e.target)) return
  open.value = false
}

// v3.3.21 面板接管滑动：只有消息列表 / 订阅区确实还能往这个方向滚时才让它滚，
// 其他情况（内容不够长滚不动、已经滚到头、手指在标题栏上）一律拦下，不让后面的页面跟着动。
// overscroll-behavior 只在元素真的可滚动时生效，列表短的时候拦不住，所以这里自己判断。
const SCROLLER = '.note-list, .note-subs'
function canScroll(el, dy) {
  if (!el || el.scrollHeight <= el.clientHeight + 1) return false
  if (dy < 0) return el.scrollTop > 0 // 手指往下拉 / 滚轮往上：内容要往上回
  return el.scrollTop + el.clientHeight < el.scrollHeight - 1
}
let touchY = 0
function onPanelTouchStart(e) {
  touchY = e.touches[0]?.clientY ?? 0
}
function onPanelTouchMove(e) {
  const y = e.touches[0]?.clientY ?? touchY
  const dy = touchY - y // > 0：手指上推，内容往下走
  touchY = y
  if (!canScroll(e.target.closest?.(SCROLLER), dy) && e.cancelable) e.preventDefault()
}
function onPanelWheel(e) {
  if (!canScroll(e.target.closest?.(SCROLLER), e.deltaY) && e.cancelable) e.preventDefault()
}
// 手机上面板打开期间再锁住页面本身的滚动，双保险
watch([open, phone], ([on, ph]) => document.documentElement.classList.toggle('note-lock', on && ph))
watch(
  () => authState.user?.id,
  (id) => {
    clearInterval(timer)
    noteState.items = null
    noteState.unread = 0
    noteState.subs = null
    if (id) {
      loadNotes()
      loadSubs()
      timer = setInterval(loadNotes, 5 * 60 * 1000)
    }
  },
  { immediate: true },
)
onMounted(() => {
  addEventListener('pointerdown', onDoc)
  mq?.addEventListener?.('change', onMq)
})
onBeforeUnmount(() => {
  clearInterval(timer)
  removeEventListener('pointerdown', onDoc)
  mq?.removeEventListener?.('change', onMq)
  document.documentElement.classList.remove('note-lock')
})
const ICON = { new_items: 'sparkles', release: 'trend' }
</script>

<template>
  <div v-if="authState.user" ref="root" class="relative">
    <button class="bell grid h-9 w-9 cursor-pointer place-items-center rounded-full text-ink-2 transition-colors hover:bg-hover hover:text-brand" :class="{ ringing: noteState.unread }" :aria-label="noteState.unread ? `消息，${noteState.unread} 条未读` : '消息'" :aria-expanded="open" @click="toggle">
      <Icon name="bell" :size="18" />
      <!-- v3.3.30 数字挪到铃铛右上角外侧（少挡铃铛）；有未读时不再出现圆形描边（原来的 ring 类名撞上了 Tailwind 的描边工具类） -->
      <span v-if="noteState.unread" class="pointer-events-none absolute -top-0.5 -right-1 grid h-4 min-w-4 place-items-center rounded-full bg-danger px-1 font-mono text-[10px] leading-none font-bold text-white ring-2 ring-white">{{ noteState.unread > 9 ? '9+' : noteState.unread }}</span>
    </button>
    <!-- 手机：面板外盖一层透明遮罩，手指一碰（点或滑）就收起，也不会误点到后面的卡片 -->
    <Teleport to="body" :disabled="!phone">
    <div v-if="shield && phone" class="fixed inset-0 z-[60]" aria-hidden="true" @pointerdown.prevent="dismiss" @click="shield = false" @touchmove.prevent @wheel.prevent />
    <Transition name="drop">
      <div v-if="open" ref="panel" class="note-panel glass-strong z-50 flex flex-col overflow-hidden rounded-2xl !bg-white/97 max-sm:fixed max-sm:z-[61] max-sm:inset-x-3 max-sm:top-[62px] sm:absolute sm:top-full sm:right-0 sm:mt-2 sm:w-[340px] shadow-[0_18px_40px_-14px_rgb(11_47_122/0.5)]" role="dialog" aria-label="消息" @touchstart="onPanelTouchStart" @touchmove="onPanelTouchMove" @wheel="onPanelWheel">
        <div class="flex shrink-0 items-center gap-2 border-b border-line px-4 py-2.5">
          <b class="text-[14px]">消息</b>
          <span v-if="noteState.unread" class="rounded-full bg-brand-soft px-1.5 font-mono text-[11px] leading-[18px] font-semibold text-brand">{{ noteState.unread }}</span>
          <button class="ml-auto inline-flex cursor-pointer items-center gap-1 rounded-md px-1.5 py-0.5 text-[12.5px] text-brand transition-colors hover:bg-brand-soft disabled:cursor-default disabled:text-mute disabled:hover:bg-transparent" :disabled="!noteState.unread" @click="markAllNotesRead">
            <Icon name="check" :size="13" />全部已读
          </button>
        </div>
        <!-- v3.3.7 我的订阅：已订阅的分类（点名称看上新、✕ 取消），没有就引导去订阅 -->
        <div class="note-subs shrink-0 overflow-y-auto border-b border-line-2 px-3 py-2.5">
          <div class="flex items-center gap-2">
            <span class="text-[12px] font-medium text-ink-2">我订阅的分类</span>
            <button class="ml-auto inline-flex cursor-pointer items-center gap-1 rounded-full bg-brand-soft px-2.5 py-1 text-[12px] font-medium text-brand transition-colors hover:bg-brand hover:text-white" @click="subscribeMore">
              <Icon name="plus" :size="12" />{{ noteState.subList.length ? '订阅更多' : '去订阅' }}
            </button>
          </div>
          <div v-if="noteState.subList.length" class="mt-2 flex flex-wrap gap-1.5">
            <span v-for="s in noteState.subList" :key="s.code" class="sub-chip inline-flex items-center rounded-full border border-line bg-white text-[12px]">
              <button class="cursor-pointer py-0.5 pr-1 pl-2.5 hover:text-brand" @click="openSub(s)">{{ s.name }}</button>
              <button class="grid h-5 w-5 cursor-pointer place-items-center rounded-full text-mute hover:text-danger" :aria-label="`取消订阅 ${s.name}`" @click="toggleSub(s.code, s.name)"><Icon name="x" :size="11" /></button>
            </span>
          </div>
          <p v-else class="mt-1 text-[12px] text-mute">订阅后，分类有新收录会每天汇总提醒你</p>
        </div>
        <div v-if="!noteState.items" class="space-y-2 p-3"><div v-for="n in 3" :key="n" class="skeleton-bar h-12 rounded-xl" /></div>
        <div v-else-if="!noteState.items.length" class="flex flex-col items-center gap-2 px-6 py-8 text-center text-[13px] text-mute">
          <Icon name="bell" :size="26" class="text-line" />
          <p>暂时没有消息。订阅分类或收藏项目后，有新收录、新版本会提醒你</p>
        </div>
        <ul v-else class="note-list m-0 min-h-0 flex-1 list-none overflow-y-auto overscroll-contain p-1.5">
          <li v-for="(n, i) in noteState.items" :key="n.id" class="note-row" :style="{ '--d': `${i * 30}ms` }">
            <button class="flex w-full cursor-pointer gap-2.5 rounded-xl px-2.5 py-2 text-left transition-colors hover:bg-hover" @click="go(n)">
              <span class="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-lg" :class="n.kind === 'release' ? 'bg-ok-soft text-ok' : 'bg-brand-soft text-brand'"><Icon :name="ICON[n.kind] || 'bell'" :size="15" /></span>
              <span class="min-w-0 flex-1">
                <span class="block text-[13px] leading-snug" :class="n.read ? 'text-ink-2' : 'font-semibold text-ink'">{{ n.title }}</span>
                <span v-if="n.body" class="mt-0.5 block truncate text-[12px] text-mute">{{ n.body }}</span>
                <span class="mt-0.5 block text-[11px] text-mute">{{ timeAgo(n.created_at) }}</span>
              </span>
              <span v-if="!n.read" class="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-brand" />
            </button>
          </li>
        </ul>
      </div>
    </Transition>
    </Teleport>
  </div>
</template>

<style scoped>
.bell.ringing :deep(svg) {
  animation: ring 2.4s ease-in-out infinite;
  transform-origin: 50% 10%;
}
@keyframes ring {
  0%,
  70%,
  100% {
    transform: rotate(0);
  }
  75% {
    transform: rotate(14deg);
  }
  85% {
    transform: rotate(-12deg);
  }
  92% {
    transform: rotate(6deg);
  }
}
/* v3.3.20 面板高度：手机最多半屏，电脑最多 560px；订阅标签区过高时自己滚动 */
.note-panel {
  max-height: min(560px, calc(100vh - 90px));
}
.note-subs {
  max-height: 108px;
}
@media (max-width: 639.98px) {
  .note-panel {
    max-height: 50vh;
    max-height: 50dvh;
  }
  .note-subs {
    max-height: 84px;
  }
}
.note-row {
  animation: notein 0.35s var(--ease-out-expo) both;
  animation-delay: var(--d);
}
@keyframes notein {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
}
@media (prefers-reduced-motion: reduce) {
  .bell.ringing :deep(svg),
  .note-row {
    animation: none;
  }
}
</style>
