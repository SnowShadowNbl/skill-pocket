<script setup>
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, isCancelled } from '../../api'
import { toast } from '../../composables/toast'
import AnnouncementsPanel from '../components/AnnouncementsPanel.vue'
import HomeConfigPanel from '../components/HomeConfigPanel.vue'

// 运营工具：小范围公告、首页运营位、各分类订阅人数
const route = useRoute()
const router = useRouter()
const TABS = [['announcements', '公告'], ['home', '首页运营位'], ['subs', '订阅人数']]
const tab = computed(() => (TABS.some((t) => t[0] === route.query.tab) ? route.query.tab : 'announcements'))
const setTab = (t) => router.replace({ query: { tab: t === 'announcements' ? undefined : t } })

const subs = ref(null)
async function loadSubs() {
  try {
    subs.value = await api('/api/admin/subscriptions/stats')
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  }
}
const subsOnce = computed(() => {
  if (tab.value === 'subs' && !subs.value) loadSubs()
  return true
})
const max = computed(() => Math.max(1, ...(subs.value?.items || []).map((x) => x.subscribers)))
</script>

<template>
  <div>
    <div class="flex flex-wrap items-center gap-3">
      <h1 class="m-0 text-xl font-semibold">运营工具</h1>
      <div class="seg ml-auto max-w-full overflow-x-auto [&>button]:shrink-0 [&>button]:whitespace-nowrap"><button v-for="t in TABS" :key="t[0]" :class="{ on: tab === t[0] }" @click="setTab(t[0])">{{ t[1] }}</button></div>
    </div>
    <AnnouncementsPanel v-if="tab === 'announcements'" />
    <HomeConfigPanel v-else-if="tab === 'home'" />
    <div v-else-if="subsOnce">
      <div v-if="!subs" class="skeleton mt-3 h-60" />
      <template v-else>
        <ul class="m-0 mt-3 grid list-none grid-cols-2 gap-3.5 p-0">
          <li class="card px-[18px] py-3.5"><p class="m-0 text-[13px] text-mute">订阅了分类的人</p><b class="mt-1 block text-2xl tabular-nums">{{ subs.subscribers }}</b></li>
          <li class="card px-[18px] py-3.5"><p class="m-0 text-[13px] text-mute">订阅总数</p><b class="mt-1 block text-2xl tabular-nums">{{ subs.subscriptions }}</b></li>
        </ul>
        <section class="card mt-3.5">
          <div class="card-hd"><h2>各分类订阅人数</h2></div>
          <p v-if="!subs.items.length" class="m-0 px-[18px] py-6 text-center text-[13px] text-mute">还没有人订阅</p>
          <ul v-else class="m-0 list-none p-0">
            <li v-for="x in subs.items" :key="x.category.id" class="px-[18px] py-2.5">
              <span class="flex text-[13px]"><span :class="x.category.is_parent ? 'font-semibold' : ''">{{ x.category.parent ? `${x.category.parent} / ` : '' }}{{ x.category.name }}</span><b class="ml-auto tabular-nums">{{ x.subscribers }}</b></span>
              <span class="mt-1.5 block h-1.5 overflow-hidden rounded-full bg-[#eef3fa]"><span class="block h-full rounded-full bg-primary" :style="{ width: `${Math.max(2, (x.subscribers / max) * 100)}%` }" /></span>
            </li>
          </ul>
        </section>
      </template>
    </div>
  </div>
</template>
