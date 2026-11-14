<script setup>
import { ref } from 'vue'
import { api, formatTime, isCancelled } from '../../api'
import { toast } from '../../composables/toast'

// 版本与部署：按更新日志列出每个版本，对比发布前后各 24 小时的接口错误和新出现的客户端报错
const data = ref(null)
const page = ref(1)
const CAT = { feature: ['新功能', 'tag-blue'], change: ['优化', 'tag-gray'], fix: ['修复', 'tag-ok'] }
const n = (v) => (v == null ? '未知' : v)
const rate = (r) => (r == null ? '未知' : `${Math.round(r * 10000) / 100}%`)
// 发布后比发布前更差时标红
const worse = (a, b) => a != null && b != null && b > a

async function load(more = false) {
  page.value = more ? page.value + 1 : 1
  try {
    const d = await api(`/api/admin/releases?page=${page.value}&page_size=20`)
    data.value = more ? { ...d, items: [...data.value.items, ...d.items] } : d
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  }
}
load()
</script>

<template>
  <div>
    <div v-if="!data" class="skeleton mt-3 h-60" />
    <template v-else>
      <ul class="m-0 mt-3 list-none space-y-3.5 p-0">
        <li v-for="r in data.items" :key="r.version" class="card px-[18px] py-3.5">
          <div class="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <b class="font-mono text-base">{{ r.version }}</b>
            <span class="min-w-0 flex-1 font-medium break-words">{{ r.title }}</span>
            <span class="text-xs whitespace-nowrap text-mute">{{ r.deployed_at ? formatTime(r.deployed_at) : '未知' }}</span>
          </div>
          <ul v-if="r.changes.length" class="m-0 mt-2 list-none p-0 text-[13px] text-ink-2">
            <li v-for="(c, i) in r.changes" :key="i" class="py-0.5"><span class="tag mr-1.5" :class="CAT[c.category]?.[1] || 'tag-gray'">{{ CAT[c.category]?.[0] || c.category }}</span>{{ c.title }}</li>
          </ul>
          <dl class="m-0 mt-3 grid grid-cols-3 gap-2 text-xs">
            <div class="rounded-lg bg-subtle px-3 py-2">
              <dt class="text-mute">接口 5xx</dt>
              <dd class="m-0 mt-0.5 tabular-nums" :class="{ 'text-bad': worse(r.api_5xx_before, r.api_5xx_after) }"><b>{{ n(r.api_5xx_before) }}</b> → <b>{{ n(r.api_5xx_after) }}</b></dd>
            </div>
            <div class="rounded-lg bg-subtle px-3 py-2">
              <dt class="text-mute">错误率</dt>
              <dd class="m-0 mt-0.5 tabular-nums" :class="{ 'text-bad': worse(r.error_rate_before, r.error_rate_after) }"><b>{{ rate(r.error_rate_before) }}</b> → <b>{{ rate(r.error_rate_after) }}</b></dd>
            </div>
            <div class="rounded-lg bg-subtle px-3 py-2">
              <dt class="text-mute">新出现的报错</dt>
              <dd class="m-0 mt-0.5 tabular-nums" :class="{ 'text-bad': worse(r.client_errors_before, r.client_errors_after) }"><b>{{ n(r.client_errors_before) }}</b> → <b>{{ n(r.client_errors_after) }}</b></dd>
            </div>
          </dl>
        </li>
      </ul>
      <div class="mt-3 flex items-center text-xs text-mute">
        共 {{ data.total }} 个版本 · 发布前后各 {{ data.window_hours }} 小时
        <button v-if="data.items.length < data.total" class="btn btn-sm ml-auto" @click="load(true)">加载更多</button>
      </div>
    </template>
  </div>
</template>
