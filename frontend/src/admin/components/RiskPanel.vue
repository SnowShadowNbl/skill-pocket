<script setup>
import { ref, watch } from 'vue'
import { api, isCancelled } from '../../api'
import { toast } from '../../composables/toast'
import { runBulk } from '../composables/bulk'
import { askReason } from '../composables/reason'
import { can } from '../composables/usePermissions'

// 风控：同网段集中注册、验证码被刷、疑似刷星；可以直接封网段、排除出榜单。扫码滥用没有 IP 记录，统计不了
const days = ref(7)
const data = ref(null)
const busy = ref('')
const canWrite = can('resources', 'w')
const DAYS = [[1, '24 小时'], [7, '7 天'], [30, '30 天']]
const KIND = { email: '邮箱', ip: 'IP', account: '账号' }
const ST = { active: '正常', banned: '已封禁', frozen: '已冻结', merged: '已合并', deleted: '已注销' }

async function load() {
  data.value = null
  try {
    data.value = await api(`/api/admin/risk/overview?days=${days.value}`)
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  }
}
watch(days, load, { immediate: true })

async function banNet(c) {
  const cidr = `${c.ip_prefix}.0/24`
  const reason = await askReason({ title: `封禁网段 ${cidr}`, impact: `这个网段的所有访问都会被拒绝，涉及 ${c.count} 个新注册账号；可以在用户页「IP 封禁」里解除`, templates: ['集中注册，疑似批量注册', '刷验证码'], danger: true, okText: '封禁' })
  if (reason === null) return
  busy.value = c.ip_prefix
  try {
    await api('/api/admin/ip-bans', { method: 'POST', body: { ip: cidr, reason: `风控：${reason}`, days: null } })
    toast(`已封禁 ${cidr}`, 'success')
  } catch (e) {
    toast(e.message, 'error')
  } finally {
    busy.value = ''
  }
}
async function banIp(r) {
  const reason = await askReason({ title: `封禁 IP ${r.key}`, impact: '这个 IP 访问全站都会被拒绝；可以在用户页「IP 封禁」里解除', templates: ['刷验证码'], danger: true, okText: '封禁' })
  if (reason === null) return
  busy.value = r.key
  try {
    await api('/api/admin/ip-bans', { method: 'POST', body: { ip: r.key, reason: `风控：${reason}`, days: null } })
    toast(`已封禁 ${r.key}`, 'success')
  } catch (e) {
    toast(e.message, 'error')
  } finally {
    busy.value = ''
  }
}
async function excludeItem(s) {
  const reason = await askReason({ title: `把「${s.item.name}」排除出榜单`, impact: '条目仍可搜索和访问，日榜、周榜立即重算', templates: ['疑似刷星', '星数异常增长'], danger: true, okText: '排除' })
  if (reason === null) return
  busy.value = `i${s.item.id}`
  try {
    const r = await runBulk('/api/admin/items/bulk', { action: 'rank_exclude', scope: { ids: [s.item.id] }, reason })
    if (r.fail_count) throw new Error(r.results?.[0]?.message || '没有成功')
    s.rank_excluded = true
    toast('已排除', 'success')
  } catch (e) {
    toast(e.message, 'error')
  } finally {
    busy.value = ''
  }
}
</script>

<template>
  <div>
    <div class="mt-3 flex flex-wrap items-center gap-2">
      <div class="seg"><button v-for="d in DAYS" :key="d[0]" :class="{ on: days === d[0] }" @click="days = d[0]">{{ d[1] }}</button></div>
      <router-link :to="{ path: '/resources', query: { tab: 'alerts' } }" class="btn btn-sm ml-auto no-underline">风控告警</router-link>
    </div>
    <div v-if="!data" class="skeleton mt-3 h-60" />
    <template v-else>
      <section class="card mt-3.5">
        <div class="card-hd"><h2>集中注册</h2><span class="text-xs text-mute">同一网段注册 ≥ {{ data.thresholds.register_cluster_min }} 个账号</span></div>
        <p v-if="!data.register_clusters.length" class="m-0 px-[18px] py-6 text-center text-[13px] text-mute">没有发现</p>
        <ul v-else class="m-0 list-none p-0">
          <li v-for="c in data.register_clusters" :key="c.ip_prefix" class="border-b border-line px-[18px] py-3 last:border-0">
            <div class="flex flex-wrap items-center gap-2">
              <b class="font-mono">{{ c.ip_prefix }}.0/24</b><span class="tag tag-warn">{{ c.count }} 个账号</span>
              <button v-if="canWrite" class="btn btn-sm btn-danger ml-auto" :disabled="busy === c.ip_prefix" @click="banNet(c)">封禁网段</button>
            </div>
            <p class="m-0 mt-2 flex flex-wrap gap-1.5">
              <router-link v-for="u in c.users" :key="u.id" :to="{ path: '/users', query: { id: u.id } }" class="tag tag-gray no-underline">{{ u.label }}<template v-if="u.status && u.status !== 'active'"> · {{ ST[u.status] || u.status }}</template></router-link>
            </p>
          </li>
        </ul>
      </section>

      <section class="card mt-3.5">
        <div class="card-hd"><h2>验证码被刷</h2><span class="text-xs text-mute">被限频，或发送 ≥ {{ data.thresholds.code_hot }} 次</span></div>
        <p v-if="!data.code_abuse.length" class="m-0 px-[18px] py-6 text-center text-[13px] text-mute">没有发现</p>
        <ul v-else class="m-0 list-none p-0">
          <li v-for="r in data.code_abuse" :key="r.kind + r.key" class="flex flex-wrap items-center gap-2 border-b border-line px-[18px] py-2.5 last:border-0">
            <span class="tag tag-gray">{{ KIND[r.kind] || r.kind }}</span><b class="font-mono text-[13px] break-all">{{ r.key }}</b><span class="text-[13px] text-mute">{{ r.count }} 次</span>
            <button v-if="canWrite && r.kind === 'ip'" class="btn btn-sm btn-danger ml-auto" :disabled="busy === r.key" @click="banIp(r)">封禁 IP</button>
          </li>
        </ul>
      </section>

      <section class="card mt-3.5">
        <div class="card-hd"><h2>疑似刷星</h2></div>
        <p v-if="!data.star_anomalies.length" class="m-0 px-[18px] py-6 text-center text-[13px] text-mute">没有发现</p>
        <ul v-else class="m-0 list-none p-0">
          <li v-for="s in data.star_anomalies" :key="s.item.id" class="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-line px-[18px] py-2.5 last:border-0">
            <router-link :to="{ path: '/content', query: { id: s.item.id } }" class="font-medium text-ink no-underline hover:text-primary">{{ s.item.name }}</router-link>
            <span class="font-mono text-xs break-all text-mute">{{ s.repo }}</span>
            <span class="text-[13px] tabular-nums">★ {{ s.stars }}</span>
            <span v-if="s.rank_excluded" class="tag tag-gray ml-auto">已排除出榜单</span>
            <button v-else-if="canWrite" class="btn btn-sm btn-danger ml-auto" :disabled="busy === `i${s.item.id}`" @click="excludeItem(s)">排除出榜单</button>
          </li>
        </ul>
      </section>

      <p v-if="data.qr_abuse == null" class="mx-1 mt-3.5 mb-0 text-xs text-mute">扫码滥用：未知。{{ data.note }}</p>
    </template>
  </div>
</template>
