<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterView, useRoute, useRouter } from 'vue-router'
import Icon from '../components/Icon.vue'
import MyCompares from '../components/MyCompares.vue'
import { authState, requireLogin } from '../composables/auth'
import { favState } from '../composables/favorites'
import FavoritesView from './FavoritesView.vue'

// v3.2「口袋」：PC 顶栏和手机底栏的第三项，装着「我的收藏」和「我的 AI 对比」两个标签
const route = useRoute()
const router = useRouter()
const TABS = [
  ['favorites', '我的收藏', 'heart'],
  ['compares', '我的 AI 对比', 'sparkles'],
]
const tab = computed(() => (route.query.tab === 'compares' ? 'compares' : 'favorites'))
function go(t) {
  if (t !== tab.value) router.replace({ path: '/pocket', query: t === 'favorites' ? {} : { tab: t } })
}

// 标签底块跟着滑动
const bar = ref(null)
const thumb = ref({ opacity: 0 })
function measure() {
  const el = bar.value?.querySelector('[aria-selected="true"]')
  thumb.value = el ? { width: `${el.offsetWidth}px`, transform: `translateX(${el.offsetLeft}px)`, opacity: 1 } : { opacity: 0 }
}
watch(tab, () => nextTick(measure))
onMounted(() => {
  nextTick(measure)
  addEventListener('resize', measure)
  document.fonts?.ready.then(measure)
})

onBeforeUnmount(() => removeEventListener('resize', measure))

watch(
  () => authState.ready && !authState.user,
  (guest) => guest && requireLogin('登录后打开你的口袋：收藏和 AI 对比都在这里'),
  { immediate: true },
)
</script>

<template>
  <div>
    <section class="flex flex-wrap items-end gap-x-4 gap-y-3">
      <h1 v-reveal="0" class="text-[clamp(24px,4.6vw,34px)] font-extrabold tracking-tight">
        我的<span class="text-gradient">口袋</span>
      </h1>
      <div ref="bar" v-reveal="1" class="glass relative flex w-full rounded-xl p-[3px] sm:ml-auto sm:inline-flex sm:w-auto" role="tablist" aria-label="口袋">
        <span class="pointer-events-none absolute top-[3px] bottom-[3px] left-0 rounded-[9px] bg-brand shadow-[0_8px_18px_-10px_rgb(30_86_214/0.9)] transition-[transform,width,opacity] duration-500 ease-[var(--ease-spring)]" :style="thumb" />
        <button
          v-for="t in TABS"
          :key="t[0]"
          role="tab"
          :aria-selected="tab === t[0]"
          class="relative z-[1] flex h-10 flex-1 cursor-pointer items-center justify-center gap-1.5 rounded-[9px] px-4 text-[14px] leading-5 whitespace-nowrap transition-colors duration-300 sm:flex-none"
          :class="tab === t[0] ? 'font-semibold text-white' : 'font-medium text-ink-2 hover:text-ink'"
          @click="go(t[0])"
        >
          <Icon :name="t[2]" :size="15" />{{ t[1] }}
          <!-- v3.3.24 与小程序一致：数量和文字同为 14px，未选中的文字加粗到 medium -->
          <span v-if="t[0] === 'favorites' && favState.count" class="text-[14px] tabular-nums opacity-75">{{ favState.count }}</span>
        </button>
      </div>
    </section>

    <div class="mt-5">
      <Transition name="list-fade" mode="out-in">
        <FavoritesView v-if="tab === 'favorites'" key="fav" embedded base-path="/pocket" />
        <MyCompares v-else-if="authState.user" key="cmp" />
        <div v-else key="guest" class="panel mx-auto flex max-w-md flex-col items-center gap-3 px-6 py-14 text-center">
          <span class="float-y grid h-14 w-14 place-items-center rounded-2xl bg-brand text-white"><Icon name="pocket" :size="26" /></span>
          <p class="text-lg font-semibold">登录后打开你的口袋</p>
          <button class="btn-primary mt-1" @click="requireLogin()">登录 / 注册</button>
        </div>
      </Transition>
    </div>

    <!-- 详情抽屉 -->
    <RouterView v-slot="{ Component }">
      <Transition name="sheet">
        <component :is="Component" v-if="Component" />
      </Transition>
    </RouterView>
  </div>
</template>
