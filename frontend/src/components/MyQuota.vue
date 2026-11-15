<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { api, formatTime } from '../api'
import { openBindWechat, quotaPopup } from '../composables/quota'
import Icon from './Icon.vue'

// 我的 AI 额度（v2.6）：余额、今天 / 近 30 天用量、每天的用量柱状、充值与调整记录
const q = ref(null)
const error = ref('')

async function load() {
  try {
    q.value = await api('/api/auth/me/quota')
  } catch (e) {
    error.value = e.message
  }
}
onMounted(load)
watch(() => quotaPopup.boundAt, load) // 弹窗里绑定微信、领到额度后刷新

const wan = (n) => (n >= 10000 && n % 10000 === 0 ? `${n / 10000} 万` : Number(n).toLocaleString())
const fmt = (n) => (Math.abs(n) >= 10000 ? `${(n / 10000).toFixed(Math.abs(n) >= 1e6 ? 0 : 1)} 万` : String(n))
const max = computed(() => Math.max(1, ...(q.value?.series || []).map((d) => d.used)))
const pct = computed(() => (q.value && q.value.granted_total ? Math.max(0, Math.min(100, (q.value.balance / q.value.granted_total) * 100)) : 0))
const low = computed(() => q.value && !q.value.unlimited && !q.value.needs_wechat && q.value.balance < q.value.granted_total * 0.1)
</script>

<template>
  <section class="panel p-5">
    <div class="flex flex-wrap items-baseline gap-x-3 gap-y-1">
      <h2 class="section-title">AI 额度</h2>
    </div>
    <p v-if="error" class="mt-3 text-sm text-danger">{{ error }}</p>
    <div v-else-if="!q" class="skeleton-bar mt-4 h-28 rounded-2xl" />
    <template v-else>
      <div class="mt-4 grid gap-4 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
        <div>
          <p class="text-xs text-mute">剩余额度</p>
          <p class="mt-1 text-[30px] leading-none font-bold tabular-nums" :class="q.needs_wechat ? 'text-mute' : q.balance <= 0 ? 'text-danger' : low ? 'text-warn' : ''">{{ q.balance.toLocaleString() }}</p>
          <div class="mt-3 h-1.5 overflow-hidden rounded-full bg-ink/10"><div class="h-full rounded-full bg-brand" :style="{ width: pct + '%' }" /></div>
          <p class="mt-2 text-[12.5px] text-ink-2">
            今天用了 <b class="tabular-nums">{{ fmt(q.used_today) }}</b> · 近 30 天 <b class="tabular-nums">{{ fmt(q.used_30d) }}</b>
          </p>
          <p v-if="q.unlimited" class="mt-2 text-[12.5px] text-ok">管理员账号不受额度限制，用量照常记录</p>
          <button v-else-if="q.needs_wechat" class="btn-primary btn-sm mt-3 w-full justify-center sm:w-auto" @click="openBindWechat"><Icon name="message" :size="15" />绑定微信领取 {{ wan(q.free_amount) }} 额度</button>
          <p v-else-if="q.balance <= 0" class="mt-2 flex items-start gap-1.5 text-[12.5px] text-danger"><Icon name="alert" :size="14" class="mt-0.5 shrink-0" />额度已用完，暂时不能发起新的 AI 操作，可以联系管理员补充额度。</p>
          <p v-else-if="low" class="mt-2 text-[12.5px] text-warn">额度快用完了，需要时可以联系管理员补充</p>
          <p v-if="!q.unlimited && !q.needs_wechat && q.balance > 0 && q.estimates?.length" class="mt-2 text-[12px] text-mute">约可{{ q.estimates.slice(0, 3).map((e) => `${e.label} ${e.times.toLocaleString()} 次`).join(' · ') }}</p>
        </div>
        <div>
          <p class="text-xs text-mute">近 30 天每天的用量</p>
          <div class="mt-2 flex h-24 items-end gap-[3px]" role="img" :aria-label="`近 30 天用量，合计 ${q.used_30d}`">
            <span
              v-for="d in q.series" :key="d.day"
              class="min-w-0 flex-1 rounded-t-[3px]"
              :class="d.used ? 'bg-brand/70' : 'bg-ink/8'"
              :style="{ height: d.used ? Math.max(6, (d.used / max) * 100) + '%' : '4px' }"
              :title="`${d.day}：${d.used.toLocaleString()}`"
            />
          </div>
          <div class="mt-1 flex justify-between text-[11px] text-mute"><span>{{ q.series[0]?.day.slice(5) }}</span><span>今天</span></div>
        </div>
      </div>
      <div v-if="q.ledger.length" class="mt-5">
        <p class="text-xs text-mute">额度记录</p>
        <ul class="mt-2 divide-y divide-ink/5">
          <li v-for="r in q.ledger" :key="r.id" class="flex items-center gap-3 py-2 text-[13px]">
            <span class="w-20 shrink-0 text-ink-2">{{ r.kind_label }}</span>
            <span class="min-w-0 flex-1 truncate text-mute">{{ r.note }}</span>
            <span class="shrink-0 font-semibold tabular-nums" :class="r.delta >= 0 ? 'text-ok' : 'text-danger'">{{ r.delta >= 0 ? '+' : '' }}{{ r.delta.toLocaleString() }}</span>
            <time class="hidden shrink-0 text-xs text-mute sm:block">{{ formatTime(r.created_at) }}</time>
          </li>
        </ul>
      </div>
    </template>
  </section>
</template>
