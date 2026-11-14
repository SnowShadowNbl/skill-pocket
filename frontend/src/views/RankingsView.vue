<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'
import { api, formatStars } from '../api'
import { groupStyle, kindStyle } from '../categoryStyle'
import AiTag from '../components/AiTag.vue'
import DatePicker from '../components/DatePicker.vue'
import { authState, isAdminUser } from '../composables/auth'
import { isSubscribed, loadSubs, noteState, toggleSub } from '../composables/notifications'
import Icon from '../components/Icon.vue'
import Seg from '../components/Seg.vue'
import { loadMeta, meta } from '../composables/meta'

const route = useRoute()
const router = useRouter()

const data = ref(null)
const tree = ref([])
const loading = ref(true)
const error = ref('')

const period = computed(() => route.query.period || 'daily')
const group = computed(() => route.query.group || '')
const day = computed(() => route.query.date || '')
const kind = computed(() => route.query.kind || '')
const kinds = computed(() => meta.data?.kinds || [])
// 中文详解默认展开；用户收起后记住
const showBlurb = ref(readPref())
function readPref() {
  try {
    return localStorage.getItem('skillpocket.rankBlurb') !== '0'
  } catch {
    return true
  }
}
function toggleBlurb() {
  showBlurb.value = !showBlurb.value
  try {
    localStorage.setItem('skillpocket.rankBlurb', showBlurb.value ? '1' : '0')
  } catch {}
}

const PERIODS = [
  ['daily', '日榜'],
  ['weekly', '周榜'],
  ['monthly', '月榜'],
]
const PERIOD_LABEL = { daily: '日榜', weekly: '周榜 · 近 7 天', monthly: '月榜 · 近 30 天' }

// v3.3 分类热度趋势：各大类近 7 天星标增量，和再往前 7 天比涨跌
const trends = ref([])
api('/api/rankings/trends').then((r) => (trends.value = r)).catch(() => {})
if (authState.user && !noteState.subs) loadSubs()
const maxTrend = computed(() => Math.max(1, ...trends.value.map((t) => t.stars)))
const fmtK = (n) => (n >= 10000 ? `${(n / 1000).toFixed(n >= 100000 ? 0 : 1)}k` : n.toLocaleString())


function setQuery(patch) {
  const q = { ...route.query, ...patch }
  for (const k of Object.keys(q)) if (!q[k] || (k === 'period' && q[k] === 'daily')) delete q[k]
  router.replace({ path: '/rankings', query: q })
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const p = new URLSearchParams({ period: period.value, group: group.value, kind: kind.value })
    if (day.value) p.set('date', day.value)
    data.value = await api(`/api/rankings?${p}`)
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

const MEDAL = ['bg-brand text-white', 'bg-brand-2 text-white', 'bg-sky text-white']

// 切换日榜 / 周榜：先清掉上一份数据，显示骨架屏，避免周榜下还显示着日榜的数字
watch(period, () => (data.value = null))
watch([period, group, day, kind], () => route.path === '/rankings' && load())
watch(() => authState.version, () => load())

onMounted(async () => {
  load()
  loadMeta()
  try {
    tree.value = await api('/api/categories')
  } catch {}
})
</script>

<template>
  <div>
    <h1 v-reveal="0" class="m-0 text-2xl leading-8 font-semibold tracking-[-0.025em] md:text-[32px] md:leading-10">
      星标增速 <em class="text-gradient not-italic">榜单</em>
    </h1>

    <!-- v3.2：榜单类型、详解开关、日期在手机上也挤在一行 -->
    <div class="mt-5 flex items-center gap-1.5 sm:flex-wrap sm:gap-2">
      <Seg :model-value="period" label="榜单类型" :options="PERIODS" @update:model-value="(v) => setQuery({ period: v, date: '' })" />
      <button class="btn-ghost btn-sm shrink-0 px-2 whitespace-nowrap sm:px-3" :aria-pressed="showBlurb" :title="showBlurb ? '收起详解' : '展开详解'" @click="toggleBlurb">
        <Icon name="file-text" :size="15" /><span class="max-[400px]:hidden">{{ showBlurb ? '收起' : '展开' }}</span><span class="hidden sm:inline">详解</span>
      </button>
      <DatePicker
        v-if="data"
        class="ml-auto"
        :model-value="data.date || ''"
        :available="data.dates || []"
        :label="`选择${PERIODS.find((p) => p[0] === period)?.[1] || '榜单'}日期`"
        empty-text="还没有榜单"
        @update:model-value="(d) => setQuery({ date: d })"
      />
    </div>

    <!-- v3.3 分类热度趋势 -->
    <div v-if="trends.length" class="scrollbar-none -mx-4 mt-4 overflow-x-auto px-4">
      <div class="flex w-max gap-2">
        <button
          v-for="(t, i) in trends"
          :key="t.code"
          v-reveal="i"
          class="rp relative flex w-[132px] shrink-0 cursor-pointer flex-col overflow-hidden rounded-[10px] border px-3 py-2 text-left transition-[border-color,transform] duration-300 hover:-translate-y-0.5"
          :class="group === t.code ? 'border-brand bg-brand-soft' : 'border-line bg-white/70 hover:border-brand'"
          @click="setQuery({ group: group === t.code ? '' : t.code })"
        >
          <span class="flex items-center gap-1 pr-6 text-[12px] text-ink-2"><Icon :name="groupStyle(t.code).icon" :size="12" />{{ t.name }}</span>
          <!-- v3.3.7 订阅这个大类的上新 -->
          <span
            role="button"
            tabindex="0"
            class="absolute top-1.5 right-1.5 grid h-6 w-6 place-items-center rounded-full transition-colors"
            :class="isSubscribed(t.code) ? 'bg-brand text-white' : 'text-mute hover:bg-brand-soft hover:text-brand'"
            :title="isSubscribed(t.code) ? `已订阅「${t.name}」上新，点击取消` : `订阅「${t.name}」上新`"
            :aria-label="isSubscribed(t.code) ? `取消订阅 ${t.name}` : `订阅 ${t.name} 上新`"
            @click.stop="toggleSub(t.code, t.name)"
            @keydown.enter.stop="toggleSub(t.code, t.name)"
          ><Icon :name="isSubscribed(t.code) ? 'check' : 'bell'" :size="12" /></span>
          <span class="mt-0.5 flex items-baseline gap-1.5">
            <b class="font-mono text-[15px] font-semibold text-ink tabular-nums">+{{ fmtK(t.stars) }}</b>
            <span v-if="t.change != null" class="font-mono text-[11px] font-semibold" :class="t.change >= 0 ? 'text-ok' : 'text-danger'">{{ t.change >= 0 ? '↑' : '↓' }}{{ Math.abs(t.change) }}%</span>
          </span>
          <span class="absolute inset-x-0 bottom-0 h-[3px] bg-line-2"><i class="trend-bar block h-full bg-brand" :style="{ '--w': `${Math.max(4, Math.round((t.stars / maxTrend) * 100))}%` }" /></span>
        </button>
      </div>
    </div>

    <div v-if="kinds.length" class="scrollbar-none -mx-4 mt-3 overflow-x-auto px-4">
      <Seg :model-value="kind" variant="soft" label="使用类型" class="w-max" :options="[['', '全部类型'], ...kinds.map((k) => [k.key, k.name, kindStyle(k.key).icon])]" @update:model-value="(v) => setQuery({ kind: v })" />
    </div>

    <div class="scrollbar-none -mx-4 mt-3 flex gap-2 overflow-x-auto px-4 pb-1">
      <button
        class="rp flex h-8 shrink-0 cursor-pointer items-center rounded-full border px-3 text-[12.5px] transition-[color,background-color,border-color,transform] duration-300 active:scale-95"
        :class="!group ? 'border-transparent bg-brand text-white shadow-[0_6px_14px_-8px_rgb(30_86_214/0.9)]' : 'border-line bg-white/60 text-ink-2 hover:border-brand hover:text-brand'"
        @click="setQuery({ group: '' })"
      >全部分类</button>
      <button
        v-for="g in tree"
        :key="g.code"
        class="rp flex h-8 shrink-0 cursor-pointer items-center gap-1.5 rounded-full border px-3 text-[12.5px] transition-[color,background-color,border-color,transform] duration-300 active:scale-95"
        :class="group === g.code ? 'border-transparent bg-brand text-white shadow-[0_6px_14px_-8px_rgb(30_86_214/0.9)]' : 'border-line bg-white/60 text-ink-2 hover:border-brand hover:text-brand'"
        @click="setQuery({ group: g.code })"
      >
        <Icon :name="groupStyle(g.code).icon" :size="14" />{{ g.name }}
      </button>
    </div>

    <p v-if="error" class="mt-4 flex items-center gap-2 rounded-2xl bg-danger-soft p-3.5 text-sm text-danger" role="alert"><Icon name="alert" :size="16" />{{ error }}</p>

    <div v-if="loading && !data" class="mt-5 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
      <div v-for="n in 3" :key="n" class="panel space-y-3 p-5">
        <div class="skeleton-bar h-5 w-1/3 rounded-lg" />
        <div v-for="m in 4" :key="m" class="skeleton-bar h-10 rounded-xl" />
      </div>
    </div>

    <div v-else-if="data && !data.boards.length" class="panel mt-5 flex flex-col items-center gap-3 px-6 py-14 text-center">
      <span class="grid h-12 w-12 place-items-center rounded-lg bg-brand-soft text-brand"><Icon name="trend" :size="22" /></span>
      <p class="font-semibold">{{ data.dates.length ? '这个分类当天没有上榜条目' : '榜单还在积累数据' }}</p>
      <a v-if="isAdminUser()" href="/admin/jobs" class="btn-glass btn-sm">查看采集任务</a>
    </div>

    <Transition v-else-if="data" name="list-fade" mode="out-in">
      <div :key="`${data.period}-${data.date}-${group}`" class="mt-5 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        <section v-for="(b, bi) in data.boards" :key="b.category.id" v-reveal="bi" class="panel min-w-0 p-4 sm:p-5">
          <header class="flex items-center gap-2.5">
            <span class="grid h-9 w-9 place-items-center rounded-xl" :style="{ background: groupStyle(b.category.group_code).bg, color: groupStyle(b.category.group_code).fg }">
              <Icon :name="groupStyle(b.category.group_code).icon" :size="18" />
            </span>
            <div class="min-w-0">
              <h2 class="truncate font-semibold">{{ b.category.name }}</h2>
              <p class="text-xs text-mute">{{ b.category.group_name }} · {{ PERIOD_LABEL[data.period] }}</p>
            </div>
          </header>
          <ol class="mt-3 space-y-1.5">
            <li v-for="e in b.entries" :key="e.item.id">
              <RouterLink
                :to="{ path: `/rankings/items/${e.item.id}`, query: route.query }"
                class="group flex cursor-pointer flex-wrap items-center gap-x-3 rounded-[8px] px-2 py-2 transition-colors duration-300 hover:bg-white/70"
              >
                <span
                  class="grid h-7 w-7 shrink-0 place-items-center rounded-lg text-xs font-bold"
                  :class="e.rank <= 3 ? MEDAL[e.rank - 1] : 'bg-hover text-ink-2'"
                >{{ e.rank }}</span>
                <div class="min-w-0 flex-1">
                  <p class="truncate text-[14.5px] font-medium group-hover:text-brand">{{ e.item.name }}</p>
                  <!-- v3.2：收起详解时第二行给一句中文简介，展开时详解在下面，这里留仓库名 -->
                  <p v-if="!showBlurb && e.item.summary" class="truncate text-xs text-ink-2">{{ e.item.summary }}</p>
                  <p v-else class="truncate text-xs text-mute">{{ e.item.repo_full_name }}</p>
                </div>
                <div class="shrink-0 text-right">
                  <p class="flex items-center justify-end gap-0.5 text-sm font-semibold text-ok tabular-nums"><Icon name="trend" :size="13" />+{{ e.stars_delta.toLocaleString() }}</p>
                  <p class="text-xs text-mute tabular-nums">{{ formatStars(e.stars_end) }} 星</p>
                </div>
                <div v-if="showBlurb && e.item.rank_blurb" class="mt-1 w-full pl-10">
                  <p class="text-[12.5px] leading-relaxed text-ink-2">{{ e.item.rank_blurb }}</p>
                  <AiTag v-if="e.rank === 1" :model="e.item.rank_blurb_model" class="mt-1" />
                </div>
              </RouterLink>
            </li>
          </ol>
        </section>
      </div>
    </Transition>

    <RouterView v-slot="{ Component }">
      <Transition name="sheet">
        <component :is="Component" v-if="Component" />
      </Transition>
    </RouterView>
  </div>
</template>

<style scoped>
.trend-bar {
  width: var(--w);
  transform-origin: 0 50%;
  animation: trendgrow 0.9s var(--ease-out-expo) both;
}
@keyframes trendgrow {
  from {
    transform: scaleX(0);
  }
}
</style>
