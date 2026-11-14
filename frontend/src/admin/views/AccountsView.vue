<script setup>
import { computed, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { api, formatTime, isCancelled } from '../../api'
import { toast } from '../../composables/toast'
import ALineChart from '../components/ALineChart.vue'

// 账号关系：账号构成、注册渠道与各端登录、绑定 / 合并趋势、扫码漏斗、客户端版本
const route = useRoute()
const router = useRouter()
const DAYS = [7, 30, 90]
const days = computed(() => (DAYS.includes(Number(route.query.days)) ? Number(route.query.days) : 30))
const setDays = (d) => router.replace({ query: { ...route.query, days: d === 30 ? undefined : d } })
const ov = ref(null)

async function load() {
  try {
    ov.value = await api(`/api/admin/accounts/overview?days=${days.value}`)
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  }
}
// 客户端版本：按端和版本统计用户和会话（报错数等报错上报上线后再有）
const cv = ref(null)
async function loadVersions() {
  try {
    cv.value = (await api(`/api/admin/client-versions?days=${days.value}`)).by_client
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  }
}
// 站内消息已读率（点「全部已读」也算已读，所以会偏高）
const msg = ref(null)
async function loadMsg() {
  try {
    msg.value = await api(`/api/admin/messages/stats?days=${days.value}`)
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  }
}
const rateText = (v) => (v == null ? '未知' : `${Math.round(v * 1000) / 10}%`)
watch(days, () => { load(); loadMsg(); loadVersions() }, { immediate: true })

// 账号构成：前四类是有效账号（可点进用户列表），已合并 / 已注销单列
const COMP = [
  { key: 'email_only', color: '#1e56d6', to: { login: 'email_only' } },
  { key: 'wechat_only', color: '#12a150', to: { login: 'wechat_only' } },
  { key: 'both', color: '#5aa2ff', to: { login: 'both' } },
  { key: 'password_only', color: '#8592a6' },
]
const SIDE = [{ key: 'merged', to: { status: 'merged' } }, { key: 'deleted', to: { status: 'deleted' } }]
const compTotal = computed(() => COMP.reduce((n, c) => n + (ov.value?.composition[c.key]?.count || 0), 0))
const pct = (n, total) => (total ? Math.max(n ? 2 : 0, (n / total) * 100) : 0)

// 渠道：key 为空串表示「未知」，用户列表里对应 channel=unknown
const CHANNELS = ['web-pc', 'web-mobile', 'miniprogram', '']
const channelTotal = (m) => CHANNELS.reduce((n, k) => n + (m?.[k]?.count || 0), 0)
const channelTo = (k) => ({ channel: k || 'unknown' })

const SERIES = [
  { key: 'register', label: '注册', color: '#1e56d6' },
  { key: 'bind_wechat', label: '绑定微信', color: '#12a150' },
  { key: 'bind_email', label: '绑定邮箱', color: '#5aa2ff' },
  { key: 'merge_account', label: '账号合并', color: '#45546b' },
  { key: 'bind_conflict', label: '绑定冲突', color: '#e5484d' },
  { key: 'unbind_wechat', label: '解绑微信', color: '#d97706', dashed: true },
  { key: 'delete_account', label: '注销账号', color: '#8592a6', dashed: true },
]
const rate = (v) => (v == null ? '—' : `${Math.round(v * 1000) / 10}%`)
const FUNNEL_STEPS = [['created', '生成'], ['scanned', '已扫码'], ['done', '已确认']]
const funnelMax = (f) => Math.max(1, f.created, f.scanned, f.done)
</script>

<template>
  <div>
    <div class="flex flex-wrap items-center gap-3">
      <h1 class="m-0 text-xl font-semibold">账号关系</h1>
      <div class="seg ml-auto">
        <button v-for="d in DAYS" :key="d" :class="{ on: days === d }" @click="setDays(d)">{{ d }} 天</button>
      </div>
    </div>

    <div v-if="!ov" class="mt-5 grid gap-3.5"><div class="skeleton h-40" /><div class="skeleton h-60" /></div>
    <template v-else>
      <!-- 账号构成 -->
      <section class="card mt-5">
        <div class="card-hd"><h2>账号构成</h2></div>
        <div class="card-bd">
          <div class="flex flex-wrap items-end gap-x-8 gap-y-3">
            <div><p class="m-0 text-[13px] text-mute">有效用户</p><b class="text-3xl tabular-nums">{{ ov.effective_users }}</b></div>
            <div class="flex gap-6">
              <RouterLink v-for="s in SIDE" :key="s.key" :to="{ path: '/users', query: s.to }" class="group no-underline">
                <p class="m-0 text-[13px] text-mute">{{ ov.composition[s.key].label }}</p>
                <b class="text-xl tabular-nums text-ink group-hover:text-primary">{{ ov.composition[s.key].count }}</b>
              </RouterLink>
            </div>
          </div>
          <div class="mt-4 flex h-3 overflow-hidden rounded-full bg-[#eef3fa]" role="img" aria-label="账号构成">
            <span v-for="c in COMP" :key="c.key" :style="{ width: `${pct(ov.composition[c.key].count, compTotal)}%`, background: c.color }" :title="`${ov.composition[c.key].label} ${ov.composition[c.key].count}`" />
          </div>
          <ul class="m-0 mt-3 grid list-none grid-cols-2 gap-2 p-0 sm:grid-cols-4">
            <li v-for="c in COMP" :key="c.key">
              <component :is="c.to ? RouterLink : 'div'" :to="c.to ? { path: '/users', query: c.to } : undefined" class="flex items-center gap-2 rounded-md px-2 py-2 text-[13px] text-ink no-underline" :class="c.to ? 'hover:bg-subtle' : ''">
                <i class="h-2.5 w-2.5 shrink-0 rounded-sm" :style="{ background: c.color }" />
                <span class="text-ink-2">{{ ov.composition[c.key].label }}</span>
                <b class="ml-auto tabular-nums">{{ ov.composition[c.key].count }}</b>
              </component>
            </li>
          </ul>
        </div>
      </section>

      <!-- 渠道 -->
      <div class="mt-3.5 grid gap-3.5 md:grid-cols-2">
        <section v-for="blk in [{ title: '注册渠道', m: ov.signup_channels, link: true }, { title: `各端登录（${ov.days} 天内累计）`, m: ov.logins_by_client }]" :key="blk.title" class="card">
          <div class="card-hd"><h2>{{ blk.title }}</h2></div>
          <ul class="m-0 list-none p-0">
            <li v-for="k in CHANNELS" :key="k || 'unknown'">
              <component :is="blk.link ? RouterLink : 'div'" :to="blk.link ? { path: '/users', query: channelTo(k) } : undefined" class="block px-[18px] py-2.5 text-ink no-underline" :class="blk.link ? 'hover:bg-subtle' : ''">
                <span class="flex items-baseline text-[13px]"><span :class="k ? '' : 'text-mute'">{{ blk.m[k]?.label || '未知' }}</span><b class="ml-auto tabular-nums">{{ blk.m[k]?.count || 0 }}</b></span>
                <span class="mt-1.5 block h-1.5 overflow-hidden rounded-full bg-[#eef3fa]"><span class="block h-full rounded-full" :class="k ? 'bg-primary' : 'bg-mute/50'" :style="{ width: `${pct(blk.m[k]?.count || 0, channelTotal(blk.m))}%` }" /></span>
              </component>
            </li>
          </ul>
        </section>
      </div>

      <!-- 趋势 -->
      <section class="card mt-3.5">
        <div class="card-hd"><h2>绑定与合并趋势</h2></div>
        <div class="card-bd">
          <ul class="m-0 mb-4 grid list-none grid-cols-2 gap-2 p-0 sm:grid-cols-4 lg:grid-cols-7">
            <li v-for="s in SERIES" :key="s.key" class="rounded-lg px-3 py-2" :class="s.key === 'bind_conflict' && ov.totals[s.key].count ? 'bg-bad-soft' : 'bg-subtle'">
              <p class="m-0 text-xs" :class="s.key === 'bind_conflict' && ov.totals[s.key].count ? 'text-bad' : 'text-mute'">{{ ov.totals[s.key].label }}</p>
              <b class="text-lg tabular-nums" :class="s.key === 'bind_conflict' && ov.totals[s.key].count ? 'text-bad' : ''">{{ ov.totals[s.key].count }}</b>
            </li>
          </ul>
          <ALineChart :data="ov.trend" :series="SERIES" />
          <RouterLink v-if="ov.totals.bind_conflict.count" :to="{ path: '/activity', query: { result: 'failed' } }" class="mt-2 inline-block text-[13px] text-bad">查看绑定冲突记录</RouterLink>
        </div>
      </section>

      <!-- 扫码漏斗 -->
      <div class="mt-3.5 grid gap-3.5 md:grid-cols-2">
        <section v-for="k in ['login', 'bind']" :key="k" class="card">
          <div class="card-hd"><h2>{{ ov.qr_funnel[k].label }}</h2></div>
          <div class="card-bd">
            <ul class="m-0 list-none p-0">
              <li v-for="[step, name] in FUNNEL_STEPS" :key="step" class="mb-3 last:mb-0">
                <span class="flex items-baseline text-[13px]"><span class="text-ink-2">{{ name }}</span><b class="ml-auto tabular-nums">{{ ov.qr_funnel[k][step] }}</b></span>
                <span class="mt-1.5 block h-2 overflow-hidden rounded-full bg-[#eef3fa]"><span class="block h-full rounded-full bg-primary" :style="{ width: `${(ov.qr_funnel[k][step] / funnelMax(ov.qr_funnel[k])) * 100}%` }" /></span>
              </li>
            </ul>
            <div class="mt-4 grid grid-cols-2 gap-2 text-[13px]">
              <div class="rounded-lg bg-subtle px-3 py-2"><p class="m-0 text-xs text-mute">扫码率</p><b class="tabular-nums">{{ rate(ov.qr_funnel[k].scan_rate) }}</b></div>
              <div class="rounded-lg bg-subtle px-3 py-2"><p class="m-0 text-xs text-mute">确认率</p><b class="tabular-nums">{{ rate(ov.qr_funnel[k].done_rate) }}</b></div>
              <div class="col-span-2 flex items-center rounded-lg px-3 py-2" :class="ov.qr_funnel[k].scanned_not_confirmed ? 'bg-warn-soft text-warn' : 'bg-subtle'">
                <span :class="ov.qr_funnel[k].scanned_not_confirmed ? '' : 'text-mute'">已扫码未确认</span><b class="ml-auto tabular-nums">{{ ov.qr_funnel[k].scanned_not_confirmed }}</b>
              </div>
            </div>
            <p class="m-0 mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-mute">
              <span>未扫码过期 {{ ov.qr_funnel[k].expired_unscanned }}</span><span>已取消 {{ ov.qr_funnel[k].canceled }}</span><span>等待中 {{ ov.qr_funnel[k].waiting }}</span>
            </p>
          </div>
        </section>
      </div>

      <!-- 站内消息已读率 -->
      <section v-if="msg" class="card mt-3.5">
        <div class="card-hd"><h2>站内消息已读率</h2><span class="text-xs text-mute">近 {{ msg.days }} 天</span></div>
        <div class="card-bd">
          <ul class="m-0 grid list-none grid-cols-3 gap-2.5 p-0">
            <li class="rounded-lg bg-subtle px-3 py-2"><p class="m-0 text-xs text-mute">发出</p><b class="text-lg tabular-nums">{{ msg.sent }}</b></li>
            <li class="rounded-lg bg-subtle px-3 py-2"><p class="m-0 text-xs text-mute">已读</p><b class="text-lg tabular-nums">{{ msg.read }}</b></li>
            <li class="rounded-lg bg-subtle px-3 py-2"><p class="m-0 text-xs text-mute">已读率</p><b class="text-lg tabular-nums">{{ rateText(msg.read_rate) }}</b></li>
          </ul>
          <table v-if="msg.by_type.length" class="tbl mt-3">
            <thead><tr><th>类型</th><th class="text-right">发出</th><th class="text-right">已读</th><th class="text-right">已读率</th></tr></thead>
            <tbody><tr v-for="t in msg.by_type" :key="t.type"><td>{{ t.label }}</td><td class="text-right tabular-nums">{{ t.sent }}</td><td class="text-right tabular-nums">{{ t.read }}</td><td class="text-right tabular-nums">{{ rateText(t.read_rate) }}</td></tr></tbody>
          </table>
        </div>
      </section>

      <!-- 客户端版本 -->
      <section class="card mt-3.5">
        <div class="card-hd"><h2>客户端版本</h2><span class="text-xs text-mute">近 {{ ov.days }} 天登录</span></div>
        <div v-if="!cv" class="card-bd"><div class="skeleton h-24" /></div>
        <template v-else>
          <div v-for="c in cv" :key="c.client" class="border-b border-line last:border-0">
            <p class="m-0 flex items-center gap-2 bg-subtle px-[18px] py-2 text-[13px]"><b class="font-semibold">{{ c.label }}</b><span class="text-xs text-mute">事件 {{ c.events.toLocaleString() }}</span></p>
            <p v-if="!c.versions.length" class="m-0 px-[18px] py-3 text-[13px] text-mute">这段时间没有登录</p>
            <div v-else class="overflow-x-auto">
              <table class="tbl">
                <thead><tr><th>版本</th><th class="text-right">用户</th><th class="text-right">会话</th><th class="hidden text-right sm:table-cell">当前用这个版本</th><th class="hidden text-right md:table-cell">报错</th><th class="hidden text-right md:table-cell">最近</th></tr></thead>
                <tbody>
                  <tr v-for="v in c.versions" :key="v.raw">
                    <td class="font-mono"><RouterLink :to="{ path: '/users', query: { client: c.client === 'unknown' ? 'unknown' : c.client, client_version: v.raw } }" class="text-ink no-underline hover:text-primary">{{ v.version }}</RouterLink></td>
                    <td class="text-right tabular-nums">{{ v.users }}</td>
                    <td class="text-right tabular-nums">{{ v.sessions }}</td>
                    <td class="hidden text-right tabular-nums sm:table-cell">{{ v.current_users ?? '未知' }}</td>
                    <td class="hidden text-right text-mute md:table-cell">{{ v.errors ?? '未知' }}</td>
                    <td class="hidden text-right text-xs whitespace-nowrap text-mute md:table-cell">{{ v.last_seen ? formatTime(v.last_seen, false) : '—' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </template>
      </section>
    </template>
  </div>
</template>
