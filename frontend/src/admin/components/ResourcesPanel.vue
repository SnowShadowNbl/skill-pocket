<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api, formatTime, isCancelled } from '../../api'
import Icon from '../../components/Icon.vue'
import { toast } from '../../composables/toast'

// 资源用量：DeepSeek 用量与余额、腾讯云邮件发送量、阿里云百炼向量用量（估算）、服务器内存 / 磁盘 / 图片增长
const emit = defineEmits(['changed'])
const d = ref(null)
const loading = ref(false)

async function load(refresh = false) {
  loading.value = true
  try {
    d.value = await api(`/api/admin/resources${refresh ? '?refresh=1' : ''}`)
    emit('changed')
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  } finally {
    loading.value = false
  }
}

function bytes(n) {
  if (n == null) return '—'
  const u = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  while (n >= 1024 && i < u.length - 1) {
    n /= 1024
    i++
  }
  return `${n.toFixed(n >= 100 || i === 0 ? 0 : 1)} ${u[i]}`
}
const num = (n) => (n == null ? '—' : n >= 1e6 ? `${(n / 1e6).toFixed(2)}M` : n >= 1e4 ? `${(n / 1e3).toFixed(1)}K` : n.toLocaleString())
const barClass = (pct) => (pct >= 90 ? 'bg-bad' : pct >= 80 ? 'bg-warn' : 'bg-primary')
const TIP = { bad: 'border-bad/30 bg-bad-soft text-bad', warn: 'border-warn/30 bg-warn-soft text-warn', ok: 'border-ok/30 bg-ok-soft text-ok' }

const ai = computed(() => d.value?.ai)
const bal = computed(() => ai.value?.balance || {})
const balLow = computed(() => bal.value.total != null && bal.value.total < d.value.thresholds.ai_balance_warn)
const maxDay = computed(() => Math.max(1, ...(ai.value?.series || []).map((x) => x.tokens)))
const emb = computed(() => d.value?.embedding)
const srv = computed(() => d.value?.server)
function uptime(s) {
  if (!s) return '—'
  const days = Math.floor(s / 86400)
  const h = Math.floor((s % 86400) / 3600)
  return days ? `${days} 天 ${h} 小时` : `${h} 小时`
}

const timer = setInterval(() => !document.hidden && load(), 60000)
onBeforeUnmount(() => clearInterval(timer))
onMounted(() => load())
</script>

<template>
  <div>
    <div class="flex justify-end">
      <button class="btn" :disabled="loading" @click="load(true)"><Icon name="refresh" :size="14" :class="{ 'animate-spin': loading }" />立即刷新</button>
    </div>

    <div v-if="!d" class="skeleton mt-5 h-96" />
    <template v-else>
      <!-- 提醒 -->
      <ul v-if="d.alerts.length" class="m-0 mt-5 list-none space-y-2 p-0">
        <li v-for="a in d.alerts" :key="a.key" class="flex items-center gap-2 rounded-lg border px-3.5 py-2.5 text-[13.5px] font-medium" :class="TIP[a.level]">
          <Icon name="alert" :size="16" />{{ a.text }}
        </li>
      </ul>

      <div class="mt-5 grid gap-3.5 xl:grid-cols-2">
        <!-- DeepSeek -->
        <section class="card">
          <div class="card-hd"><h2>DeepSeek（AI）</h2><span class="tag tag-gray">{{ ai.model || '未配置' }}</span>
            <a href="https://platform.deepseek.com/top_up" target="_blank" rel="noopener" class="btn btn-sm ml-auto" :class="{ 'btn-primary': balLow }">去充值<Icon name="external-link" :size="13" /></a></div>
          <div class="card-bd">
            <div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <div class="rounded-lg p-3" :class="balLow ? 'bg-bad-soft' : 'bg-subtle'">
                <p class="m-0 text-xs text-mute">当前余额</p>
                <b v-if="bal.total != null" class="mt-0.5 block text-xl tabular-nums" :class="{ 'text-bad': balLow }">¥{{ bal.total.toFixed(2) }}</b>
                <b v-else class="mt-0.5 block text-sm text-mute">{{ bal.error || '—' }}</b>
                <span v-if="bal.total != null" class="text-[11px] text-mute">低于 ¥{{ d.thresholds.ai_balance_warn }} 提醒</span>
              </div>
              <div class="rounded-lg bg-subtle p-3"><p class="m-0 text-xs text-mute">日均花费（按余额变化）</p><b class="mt-0.5 block text-xl tabular-nums">{{ ai.daily_spend != null ? `¥${ai.daily_spend}` : '—' }}</b>
                <span class="text-[11px] text-mute">{{ ai.days_left != null ? `约还能用 ${ai.days_left} 天` : '记录两天后可估算' }}</span></div>
              <div class="rounded-lg bg-subtle p-3"><p class="m-0 text-xs text-mute">今日调用</p><b class="mt-0.5 block text-xl tabular-nums">{{ ai.today.calls }}</b>
                <span class="text-[11px] text-mute">{{ num(ai.today.tokens_in + ai.today.tokens_out) }} tokens</span></div>
              <div class="rounded-lg bg-subtle p-3"><p class="m-0 text-xs text-mute">近 30 天</p><b class="mt-0.5 block text-xl tabular-nums">{{ num(ai.d30.tokens_in + ai.d30.tokens_out) }}</b>
                <span class="text-[11px] text-mute">{{ ai.d30.calls }} 次 · 失败 {{ ai.d30.failed }}</span></div>
            </div>
            <p class="mt-4 mb-1.5 text-xs text-mute">近 14 天 token 用量</p>
            <div class="flex h-20 items-end gap-1">
              <div v-for="x in ai.series" :key="x.day" class="group relative flex-1">
                <div class="rounded-t bg-primary/80" :style="{ height: `${Math.max(2, (x.tokens / maxDay) * 76)}px` }" />
                <span class="pointer-events-none absolute bottom-full left-1/2 z-10 mb-1 hidden -translate-x-1/2 rounded bg-ink px-1.5 py-0.5 text-[11px] whitespace-nowrap text-white group-hover:block">{{ x.day.slice(5) }} · {{ num(x.tokens) }} · {{ x.calls }} 次</span>
              </div>
            </div>
            <p class="mt-4 mb-1.5 text-xs text-mute">近 30 天用在哪里</p>
            <ul class="m-0 list-none space-y-1 p-0 text-[13px]">
              <li v-for="p in ai.by_purpose.slice(0, 8)" :key="p.purpose" class="flex gap-2"><span class="flex-1">{{ p.label }}</span><span class="text-mute tabular-nums">{{ p.calls }} 次</span><b class="w-16 text-right tabular-nums">{{ num(p.tokens) }}</b></li>
            </ul>
            <p class="mt-3 mb-0 text-[11.5px] text-mute">累计 {{ ai.all.calls }} 次调用、{{ num(ai.all.tokens_in + ai.all.tokens_out) }} tokens<template v-if="ai.first_at">（自 {{ formatTime(ai.first_at, false) }} 起）</template><template v-if="bal.checked_at"> · 余额查询于 {{ formatTime(bal.checked_at) }}</template></p>
          </div>
        </section>

        <!-- 服务器 -->
        <section class="card">
          <div class="card-hd"><h2>服务器</h2><span class="text-xs text-mute">{{ srv.cpus }} 核 · 已运行 {{ uptime(srv.uptime) }}<template v-if="srv.load"> · 负载 {{ srv.load.join(' / ') }}</template></span></div>
          <div class="card-bd">
            <div v-for="m in [
              ['运行内存', srv.memory.used_pct, `${bytes(srv.memory.used)} / ${bytes(srv.memory.total)}`, srv.memory.swap_used ? `交换分区已用 ${bytes(srv.memory.swap_used)}` : ''],
              ['存储（磁盘）', srv.disk.used_pct, `${bytes(srv.disk.used)} / ${bytes(srv.disk.total)}`, `剩余 ${bytes(srv.disk.free)}`],
            ]" :key="m[0]" class="mb-4">
              <div class="flex items-baseline gap-2 text-[13px]"><b>{{ m[0] }}</b><span class="text-mute">{{ m[2] }}</span><b class="ml-auto tabular-nums" :class="m[1] >= 90 ? 'text-bad' : m[1] >= 80 ? 'text-warn' : ''">{{ m[1] ?? '—' }}%</b></div>
              <div class="mt-1.5 h-2.5 overflow-hidden rounded-full bg-[#e9edf3]"><div class="h-full rounded-full" :class="barClass(m[1] || 0)" :style="{ width: `${m[1] || 0}%` }" /></div>
              <p v-if="m[3]" class="m-0 mt-1 text-xs text-mute">{{ m[3] }}</p>
            </div>
            <p class="mb-1.5 text-xs text-mute">数据占用</p>
            <ul class="m-0 list-none space-y-1 p-0 text-[13px]">
              <li v-for="x in srv.media" :key="x.name" class="flex gap-2"><span class="flex-1">{{ x.label }}</span><span class="text-mute tabular-nums">{{ x.files }} 个文件</span><b class="w-20 text-right tabular-nums">{{ bytes(x.bytes) }}</b></li>
              <li class="flex gap-2"><span class="flex-1">数据库</span><b class="w-20 text-right tabular-nums">{{ bytes(srv.db_size) }}</b></li>
            </ul>
            <p class="mt-3 mb-0 text-[12.5px] text-ink-2">
              <template v-if="srv.disk_growth_per_day != null">磁盘每天约增加 <b>{{ bytes(Math.max(0, srv.disk_growth_per_day)) }}</b>，</template>
              {{ srv.days_until_85 != null ? `按这个速度约 ${srv.days_until_85} 天后用到 85%。` : srv.history.length < 2 ? '增长趋势要记录两天以上才能估算（每天自动记一次）。' : '按目前的增长速度，近期不会用满。' }}
            </p>
            <ul class="m-0 mt-3 list-none space-y-1.5 p-0">
              <li v-for="(t, i) in srv.advice" :key="i" class="rounded-md border px-3 py-2 text-[12.5px]" :class="TIP[t.level]">{{ t.text }}</li>
            </ul>
          </div>
        </section>

        <!-- 阿里云百炼向量 -->
        <section class="card">
          <div class="card-hd"><h2>阿里云百炼（向量 / 语义搜索）</h2><span class="tag tag-gray">{{ emb.model }}</span>
            <a href="https://bailian.console.aliyun.com/" target="_blank" rel="noopener" class="btn btn-sm ml-auto">百炼控制台<Icon name="external-link" :size="13" /></a></div>
          <div class="card-bd">
            <p v-if="!emb.configured" class="empty">还没有配置向量接口</p>
            <template v-else>
              <div class="grid grid-cols-3 gap-3">
                <div class="rounded-lg bg-subtle p-3"><p class="m-0 text-xs text-mute">已用（估算）</p><b class="mt-0.5 block text-xl tabular-nums">{{ num(emb.tokens_used_estimate) }}</b><span class="text-[11px] text-mute">tokens</span></div>
                <div class="rounded-lg bg-subtle p-3"><p class="m-0 text-xs text-mute">近 30 天</p><b class="mt-0.5 block text-xl tabular-nums">{{ num(emb.tokens_30d) }}</b><span class="text-[11px] text-mute">24 小时 {{ num(emb.tokens_24h) }}</span></div>
                <div class="rounded-lg bg-subtle p-3"><p class="m-0 text-xs text-mute">已向量化条目</p><b class="mt-0.5 block text-xl tabular-nums">{{ emb.vectors }}</b><span class="text-[11px] text-mute">失败 {{ emb.failed }} 次</span></div>
              </div>
              <template v-if="emb.free_tokens">
                <div class="mt-4 flex items-baseline gap-2 text-[13px]"><b>免费额度</b><span class="text-mute">{{ num(emb.tokens_used_estimate) }} / {{ num(emb.free_tokens) }} tokens</span><b class="ml-auto tabular-nums">{{ emb.free_used_pct }}%</b></div>
                <div class="mt-1.5 h-2.5 overflow-hidden rounded-full bg-[#e9edf3]"><div class="h-full rounded-full" :class="barClass(emb.free_used_pct)" :style="{ width: `${emb.free_used_pct}%` }" /></div>
              </template>
              <p class="mt-3 mb-0 text-[12px] leading-relaxed text-mute">
                百炼用 API Key 查不到账户余额，这里按调用量估算：免费额度按 {{ num(emb.free_tokens) }} tokens、超出部分按 ¥{{ emb.price_per_1k }}/千 tokens 计，
                估算已产生费用 <b class="text-ink">¥{{ emb.estimated_cost }}</b>。准确余额请在百炼控制台查看。
                逐次记录从 {{ emb.logged_since ? formatTime(emb.logged_since, false) : '下一次调用' }} 开始，之前的 {{ num(emb.tokens_before_log) }} tokens 按已向量化的文本估算。
              </p>
            </template>
          </div>
        </section>

        <!-- 腾讯云邮件推送 -->
        <section class="card">
          <div class="card-hd"><h2>腾讯云邮件推送（验证码）</h2>
            <a href="https://console.cloud.tencent.com/ses" target="_blank" rel="noopener" class="btn btn-sm ml-auto">SES 控制台<Icon name="external-link" :size="13" /></a></div>
          <div class="card-bd">
            <p v-if="!d.email.configured" class="empty">还没有配置邮件服务</p>
            <template v-else>
              <div class="grid grid-cols-3 gap-3">
                <div class="rounded-lg bg-subtle p-3"><p class="m-0 text-xs text-mute">今天</p><b class="mt-0.5 block text-xl tabular-nums">{{ d.email.today }}</b><span class="text-[11px] text-mute">封</span></div>
                <div class="rounded-lg bg-subtle p-3"><p class="m-0 text-xs text-mute">本月</p><b class="mt-0.5 block text-xl tabular-nums">{{ d.email.month }}</b><span class="text-[11px]" :class="d.email.month_failed ? 'text-bad' : 'text-mute'">失败 {{ d.email.month_failed }}</span></div>
                <div class="rounded-lg bg-subtle p-3"><p class="m-0 text-xs text-mute">累计</p><b class="mt-0.5 block text-xl tabular-nums">{{ d.email.total }}</b><span class="text-[11px] text-mute">封</span></div>
              </div>
              <template v-if="d.email.monthly_quota">
                <div class="mt-4 flex items-baseline gap-2 text-[13px]"><b>本月额度</b><span class="text-mute">{{ d.email.month }} / {{ d.email.monthly_quota }}</span><b class="ml-auto tabular-nums">{{ d.email.quota_used_pct }}%</b></div>
                <div class="mt-1.5 h-2.5 overflow-hidden rounded-full bg-[#e9edf3]"><div class="h-full rounded-full" :class="barClass(d.email.quota_used_pct)" :style="{ width: `${Math.min(100, d.email.quota_used_pct)}%` }" /></div>
              </template>
              <p class="mt-3 mb-0 text-[12px] text-mute">
                本月按用途：<template v-for="(n, k) in d.email.by_purpose" :key="k">{{ { login: '登录', reset: '找回密码', change: '改密码', delete: '注销' }[k] || k }} {{ n }} 封　</template><template v-if="!Object.keys(d.email.by_purpose).length">暂无</template>
              </p>
            </template>
          </div>
        </section>
      </div>
    </template>
  </div>
</template>
