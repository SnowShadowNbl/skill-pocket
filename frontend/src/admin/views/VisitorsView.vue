<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, formatTime, isCancelled, timeAgo } from '../../api'
import Icon from '../../components/Icon.vue'
import UserAvatar from '../../components/UserAvatar.vue'
import { toast } from '../../composables/toast'
import ASelect from '../components/ASelect.vue'
import InsightsPanel from '../components/InsightsPanel.vue'

// 访客与行为（用户探真）：游客和登录用户的 IP、中文归属地、设备、来源和完整访问轨迹
const route = useRoute()
const router = useRouter()
const TABS = [['visitors', '访客'], ['events', '行为流'], ['insights', '数据洞察'], ['analysis', '数据分析']]
const tab = computed(() => (TABS.some((t) => t[0] === route.query.tab) ? route.query.tab : 'visitors'))
const setTab = (t) => router.replace({ query: { ...route.query, tab: t } })

function fail(e) {
  if (!isCancelled(e)) toast(e.message, 'error')
}

// ---------------------------------------------------------------- 访客
const vf = ref({ kind: '', q: String(route.query.q || '') })
const vPage = ref(1)
const vData = ref(null)
const kindOptions = [
  { value: '', label: '全部访客' }, { value: 'guest', label: '仅游客' }, { value: 'user', label: '已登录用户' }, { value: 'converted', label: '游客转注册' },
]
async function loadVisitors(reset = true) {
  if (reset) vPage.value = 1
  try {
    const d = await api(`/api/admin/analytics/visitors?${new URLSearchParams({ ...vf.value, page: vPage.value })}`)
    vData.value = reset ? d : { ...d, items: [...vData.value.items, ...d.items] }
  } catch (e) {
    fail(e)
  }
}

// ---------------------------------------------------------------- 行为流
const ef = ref({ name: '', q: '' })
const ePage = ref(1)
const eData = ref(null)
const nameOptions = computed(() => [{ value: '', label: '全部行为' }, ...Object.entries(eData.value?.names || {}).map(([k, v]) => ({ value: k, label: v }))])
async function loadEvents(reset = true) {
  if (reset) ePage.value = 1
  try {
    const d = await api(`/api/admin/analytics/events?${new URLSearchParams({ ...ef.value, page: ePage.value })}`)
    eData.value = reset ? d : { ...d, items: [...eData.value.items, ...d.items] }
  } catch (e) {
    fail(e)
  }
}

// ---------------------------------------------------------------- 数据洞察
const days = ref(7)
const ov = ref(null)
async function loadInsights() {
  try {
    ov.value = await api(`/api/admin/analytics/overview?days=${days.value}`)
  } catch (e) {
    fail(e)
  }
}
const maxOf = (list) => Math.max(1, ...(list || []).map((x) => x.count))

// ---------------------------------------------------------------- 访客详情
const detail = ref(null)
const detailPage = ref(1)
async function openVisitor(vid, more = false) {
  detailPage.value = more ? detailPage.value + 1 : 1
  try {
    const d = await api(`/api/admin/analytics/visitors/${encodeURIComponent(vid)}?page=${detailPage.value}`)
    detail.value = more ? { ...d, events: [...detail.value.events, ...d.events] } : d
    if (!more && route.query.vid !== vid) router.replace({ query: { ...route.query, vid } })
  } catch (e) {
    fail(e)
  }
}
function closeVisitor() {
  detail.value = null
  const { vid, ...rest } = route.query
  if (vid) router.replace({ query: rest })
}

const PAGE_NAMES = { '/': '主页', '/rankings': '榜单', '/add': '新增 Skill', '/pocket': '口袋', '/favorites': '收藏（旧）', '/me': '我的', '/manage': '旧版后台', '/terms': '用户协议', '/privacy': '隐私政策' }
function describe(e) {
  const p = e.props || {}
  if (e.item) return `「${e.item.name}」`
  if (e.name === 'search') return `「${p.q}」${p.exact ? '（只看名称匹配）' : ''}`
  if (e.name === 'page_view') {
    const m = /^\/items\/(\d+)/.exec(p.path || '')
    return PAGE_NAMES[p.path] || (m ? `详情页 #${m[1]}` : p.path || e.page)
  }
  if (e.name === 'login_open') return p.reason || ''
  if (e.name === 'login' || e.name === 'register') return p.method === 'password' ? '密码' : '邮箱验证码'
  if (e.name === 'error') return p.message || ''
  return ''
}
const CAT = { view: 'tag-blue', search: 'bg-[#f1ecff] text-[#6d4fd8]', action: 'tag-ok', account: 'tag-warn', error: 'tag-bad' }
function host(url) {
  try {
    return new URL(url).host
  } catch {
    return url
  }
}

let t
watch(vf, () => {
  clearTimeout(t)
  t = setTimeout(() => loadVisitors(), 250)
}, { deep: true })
watch(ef, () => {
  clearTimeout(t)
  t = setTimeout(() => loadEvents(), 250)
}, { deep: true })
watch(days, loadInsights)
watch(tab, (v) => {
  if (v === 'visitors' && !vData.value) loadVisitors()
  if (v === 'events' && !eData.value) loadEvents()
  if (v === 'insights' && !ov.value) loadInsights()
}, { immediate: true })

// 每 30 秒刷新第一页，看到的就是实时情况
const timer = setInterval(() => {
  if (document.hidden || detail.value) return
  if (tab.value === 'visitors' && vPage.value === 1) loadVisitors()
  else if (tab.value === 'events' && ePage.value === 1) loadEvents()
}, 30000)
onBeforeUnmount(() => clearInterval(timer))
onMounted(() => route.query.vid && openVisitor(String(route.query.vid)))
</script>

<template>
  <div>
    <div class="flex flex-wrap items-end gap-3">
      <div>
        <h1 class="m-0 text-xl font-semibold">访客与行为</h1>
        <p class="mt-1 mb-0 text-[13px] text-mute">游客和登录用户都会记录 · IP 归属地由服务器离线查询 · 明细保留 180 天</p>
      </div>
      <div class="seg ml-auto">
        <button v-for="x in TABS" :key="x[0]" :class="{ on: tab === x[0] }" @click="setTab(x[0])">{{ x[1] }}</button>
      </div>
    </div>

    <!-- 访客 -->
    <section v-if="tab === 'visitors'" class="card mt-5">
      <div class="grid gap-2.5 border-b border-line p-3.5 sm:grid-cols-[200px_1fr]">
        <ASelect v-model="vf.kind" :options="kindOptions" label="访客类型" />
        <input v-model="vf.q" type="search" class="input" placeholder="搜索 IP、地区、设备、昵称或邮箱" aria-label="搜索访客" />
      </div>
      <div v-if="!vData" class="card-bd"><div class="skeleton h-60" /></div>
      <p v-else-if="!vData.items.length" class="empty">没有符合条件的访客</p>
      <div v-else class="overflow-x-auto">
        <table class="tbl">
          <thead><tr><th>访客</th><th>位置 / IP</th><th class="hidden md:table-cell">设备</th><th class="hidden lg:table-cell">访问 / 行为</th><th class="text-right">最近活跃</th></tr></thead>
          <tbody>
            <tr v-for="v in vData.items" :key="v.vid" class="cursor-pointer" @click="openVisitor(v.vid)">
              <td>
                <span class="flex items-center gap-2">
                  <span class="h-2 w-2 shrink-0 rounded-full" :class="v.online ? 'bg-ok' : 'bg-line'" :title="v.online ? '在线' : '离线'" />
                  <template v-if="v.user"><UserAvatar :user="v.user" :size="22" /><b class="font-semibold">{{ v.user.nickname }}</b>
                    <span v-if="v.user.role === 'admin' || v.user.role === 'subadmin'" class="tag tag-blue">管理员</span></template>
                  <span v-else class="text-ink-2">游客 <span class="font-mono text-xs text-mute">{{ v.vid.slice(2, 8) }}</span></span>
                  <span v-if="v.converted_at" class="tag tag-warn">游客转注册</span>
                </span>
              </td>
              <td><span class="font-medium">{{ v.geo || '未知地区' }}</span><span class="block font-mono text-xs text-mute">{{ v.ip }}</span></td>
              <td class="hidden text-ink-2 md:table-cell">{{ v.device }}</td>
              <td class="hidden text-ink-2 tabular-nums lg:table-cell">{{ v.visits }} 次 / {{ v.events }}</td>
              <td class="text-right whitespace-nowrap text-mute">{{ timeAgo(v.last_seen) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="vData" class="flex items-center border-t border-line px-[18px] py-3 text-xs text-mute">
        共 {{ vData.total }} 位访客 · 一个浏览器算一位
        <button v-if="vData.items.length < vData.total" class="btn btn-sm ml-auto" @click="(vPage++, loadVisitors(false))">加载更多</button>
      </div>
    </section>

    <!-- 行为流 -->
    <section v-else-if="tab === 'events'" class="card mt-5">
      <div class="grid gap-2.5 border-b border-line p-3.5 sm:grid-cols-[200px_1fr]">
        <ASelect v-model="ef.name" :options="nameOptions" label="行为" />
        <input v-model="ef.q" type="search" class="input" placeholder="搜索 IP、地区或页面" aria-label="搜索行为" />
      </div>
      <div v-if="!eData" class="card-bd"><div class="skeleton h-60" /></div>
      <p v-else-if="!eData.items.length" class="empty">还没有记录</p>
      <div v-else class="overflow-x-auto">
        <table class="tbl">
          <thead><tr><th>时间</th><th>行为</th><th>内容</th><th>访客</th><th class="hidden md:table-cell">位置 / IP</th></tr></thead>
          <tbody>
            <tr v-for="e in eData.items" :key="e.id">
              <td class="whitespace-nowrap text-xs text-mute tabular-nums">{{ formatTime(e.created_at) }}</td>
              <td><span class="tag" :class="CAT[e.category]">{{ e.label }}</span></td>
              <td class="max-w-[280px] truncate">{{ describe(e) }}</td>
              <td>
                <button class="flex items-center gap-1.5 whitespace-nowrap hover:text-primary" @click="openVisitor(e.vid)">
                  <template v-if="e.user"><UserAvatar :user="e.user" :size="18" />{{ e.user.nickname }}</template>
                  <template v-else>游客 <span class="font-mono text-xs text-mute">{{ e.vid.slice(2, 8) }}</span></template>
                </button>
              </td>
              <td class="hidden md:table-cell">{{ e.geo || '未知地区' }}<span class="block font-mono text-xs text-mute">{{ e.ip }}</span></td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="eData" class="flex items-center border-t border-line px-[18px] py-3 text-xs text-mute">
        共 {{ eData.total }} 条
        <button v-if="eData.items.length < eData.total" class="btn btn-sm ml-auto" @click="(ePage++, loadEvents(false))">加载更多</button>
      </div>
    </section>

    <InsightsPanel v-else-if="tab === 'analysis'" />

    <!-- 数据洞察 -->
    <div v-else class="mt-5">
      <div class="mb-3.5 flex items-center gap-2 text-[13px] text-ink-2">
        统计范围
        <div class="seg"><button v-for="d in [7, 30, 90]" :key="d" :class="{ on: days === d }" @click="days = d">近 {{ d }} 天</button></div>
      </div>
      <div v-if="!ov" class="skeleton h-72" />
      <div v-else class="grid gap-3.5 md:grid-cols-2">
        <section v-for="blk in [
          ['热门搜索', ov.top_searches.map((x) => ({ name: x.q, count: x.count }))],
          ['热门条目', ov.top_items],
          ['行为分布', ov.events.map((x) => ({ name: x.label, count: x.count }))],
          ['设备', ov.devices],
        ]" :key="blk[0]" class="card">
          <div class="card-hd"><h2>{{ blk[0] }}</h2></div>
          <div class="card-bd">
            <p v-if="!blk[1].length" class="empty">暂无数据</p>
            <div v-for="(x, i) in blk[1]" :key="x.name + i" class="grid grid-cols-[18px_minmax(0,1fr)_minmax(0,1fr)_40px] items-center gap-2.5 py-[5px] text-[13px]">
              <span class="text-xs text-mute tabular-nums">{{ i + 1 }}</span>
              <a v-if="x.id" :href="`/items/${x.id}`" target="_blank" class="truncate hover:text-primary">{{ x.name }}</a>
              <span v-else class="truncate">{{ x.name }}</span>
              <span class="h-2 overflow-hidden rounded bg-[#eef2f8]"><i class="block h-full rounded bg-primary" :style="{ width: `${(x.count / maxOf(blk[1])) * 100}%` }" /></span>
              <em class="text-right text-ink-2 not-italic tabular-nums">{{ x.count }}</em>
            </div>
          </div>
        </section>
      </div>
    </div>

    <!-- 访客详情抽屉 -->
    <Teleport to="body">
      <Transition name="drawer">
        <div v-if="detail" class="fixed inset-0 z-40 bg-ink/30" @click.self="closeVisitor" @keydown.esc="closeVisitor">
          <aside class="absolute inset-y-0 right-0 flex w-full max-w-[560px] flex-col bg-white shadow-[-12px_0_40px_-20px_rgba(15,29,51,.35)]" role="dialog" aria-label="访客详情">
            <header class="flex items-center gap-3 border-b border-line px-5 py-4">
              <template v-if="detail.visitor.user">
                <UserAvatar :user="detail.visitor.user" :size="36" />
                <div class="min-w-0">
                  <p class="m-0 font-semibold">{{ detail.visitor.user.nickname }}
                    <span v-if="detail.visitor.converted_at" class="tag tag-warn ml-1">游客转注册</span></p>
                  <p class="m-0 truncate text-xs text-mute">{{ detail.visitor.user.email }}</p>
                </div>
              </template>
              <div v-else><p class="m-0 font-semibold">游客</p><p class="m-0 font-mono text-xs text-mute">{{ detail.visitor.vid }}</p></div>
              <button class="btn ml-auto h-9 w-9 px-0" aria-label="关闭" @click="closeVisitor"><Icon name="x" :size="17" /></button>
            </header>
            <div class="flex-1 overflow-y-auto px-5 py-4">
              <dl class="m-0 grid grid-cols-[72px_1fr] gap-x-3 gap-y-2 text-[13px]">
                <dt class="text-mute">最近位置</dt><dd class="m-0"><b>{{ detail.visitor.geo || '未知' }}</b> <span class="font-mono text-xs text-mute">{{ detail.visitor.ip }}</span></dd>
                <dt class="text-mute">首次位置</dt><dd class="m-0">{{ detail.visitor.first_geo || '未知' }} <span class="font-mono text-xs text-mute">{{ detail.visitor.first_ip }}</span></dd>
                <dt class="text-mute">设备</dt><dd class="m-0">{{ detail.visitor.device }}</dd>
                <dt class="text-mute">首次访问</dt><dd class="m-0">{{ formatTime(detail.visitor.first_seen) }}<span v-if="detail.visitor.landing" class="text-mute"> · 落地 {{ detail.visitor.landing }}</span></dd>
                <dt class="text-mute">来源</dt><dd class="m-0 break-all">{{ detail.visitor.referrer ? host(detail.visitor.referrer) : '直接访问' }}</dd>
                <dt class="text-mute">最近活跃</dt><dd class="m-0">{{ formatTime(detail.visitor.last_seen) }} · 共访问 {{ detail.visitor.visits }} 次</dd>
              </dl>

              <h3 class="mt-5 mb-2 text-[13px] font-semibold">用过的 IP</h3>
              <ul class="m-0 list-none p-0">
                <li v-for="x in detail.ips" :key="x.ip" class="flex gap-2.5 border-b border-dashed border-line py-1.5 text-[13px] last:border-0">
                  <span class="font-mono">{{ x.ip || '—' }}</span><span class="text-ink-2">{{ x.geo }}</span>
                  <span class="ml-auto text-xs text-mute">{{ x.count }} 次 · {{ timeAgo(x.last) }}</span>
                </li>
              </ul>

              <template v-if="detail.other_devices.length">
                <h3 class="mt-5 mb-2 text-[13px] font-semibold">同一账号的其他设备</h3>
                <ul class="m-0 list-none p-0">
                  <li v-for="o in detail.other_devices" :key="o.vid">
                    <button class="flex w-full gap-2.5 py-1.5 text-left text-[13px] hover:text-primary" @click="openVisitor(o.vid)">
                      <span>{{ o.device }}</span><span class="text-ink-2">{{ o.geo }}</span><span class="ml-auto text-xs text-mute">{{ timeAgo(o.last_seen) }}</span>
                    </button>
                  </li>
                </ul>
              </template>

              <h3 class="mt-5 mb-2 text-[13px] font-semibold">访问轨迹 <span class="font-normal text-mute">{{ detail.total }}</span></h3>
              <ol class="m-0 list-none border-l-2 border-line p-0 pl-4">
                <li v-for="e in detail.events" :key="e.id" class="relative py-1.5 text-[13px] before:absolute before:top-[13px] before:-left-[21px] before:h-2 before:w-2 before:rounded-full before:border-2 before:border-primary before:bg-white">
                  <div class="flex flex-wrap items-center gap-x-2">
                    <time class="text-xs text-mute tabular-nums">{{ formatTime(e.created_at) }}</time>
                    <span class="tag" :class="CAT[e.category]">{{ e.label }}</span>
                    <span class="min-w-0 break-all">{{ describe(e) }}</span>
                  </div>
                  <p class="m-0 text-[11.5px] text-mute">{{ e.geo || '未知地区' }} · <span class="font-mono">{{ e.ip }}</span></p>
                </li>
              </ol>
              <div class="mt-4 flex justify-center">
                <button v-if="detail.events.length < detail.total" class="btn btn-sm" @click="openVisitor(detail.visitor.vid, true)">更早的记录</button>
              </div>
            </div>
          </aside>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>
