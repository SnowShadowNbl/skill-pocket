<script setup>
import { computed, ref } from 'vue'
import { api, formatTime, isCancelled } from '../../api'
import Icon from '../../components/Icon.vue'
import { toast } from '../../composables/toast'

// 服务状态：数据库、磁盘、邮件、采集、AI、微信、推送、巡检、封面队列、备份；备份历史；小程序配置（只读，敏感值打码）
const emit = defineEmits(['changed'])
const health = ref(null)
const backup = ref(null)
const mini = ref(null)
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    const [h, b, m] = await Promise.all([api('/api/admin/health'), api('/api/admin/backup'), api('/api/admin/miniapp-config')])
    health.value = h
    backup.value = b
    mini.value = m
    emit('changed')
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  } finally {
    loading.value = false
  }
}
load()

const ST = { ok: ['正常', 'tag-ok', 'bg-ok'], warn: ['注意', 'tag-warn', 'bg-warn'], down: ['异常', 'tag-bad', 'bg-bad'], unknown: ['未知', 'tag-gray', 'bg-mute/50'] }
const mb = (n) => (n == null ? '未知' : n >= 1073741824 ? `${(n / 1073741824).toFixed(2)} GB` : `${(n / 1048576).toFixed(1)} MB`)
const CRAWL = { ok: '成功', failed: '失败', running: '进行中' }
const summary = (s) => (s.key === 'crawl' && s.detail?.status ? s.summary.replace(`最近一次：${s.detail.status}`, `最近一次：${CRAWL[s.detail.status] || s.detail.status}`).replace(`最近一次:${s.detail.status}`, `最近一次：${CRAWL[s.detail.status] || s.detail.status}`) : s.summary)
const yn = (v) => (v ? '是' : '否')
const tpl = computed(() => mini.value?.subscribe_templates || [])
</script>

<template>
  <div>
    <div class="flex justify-end"><button class="btn" :disabled="loading" @click="load"><Icon name="refresh" :size="14" :class="{ 'animate-spin': loading }" />重新检查</button></div>
    <div v-if="!health" class="skeleton mt-3 h-60" />
    <template v-else>
      <ul class="m-0 mt-3 grid list-none gap-3.5 p-0 sm:grid-cols-2 xl:grid-cols-3">
        <li v-for="s in health.services" :key="s.key" class="card px-[18px] py-3.5">
          <p class="m-0 flex items-center gap-2"><i class="h-2.5 w-2.5 shrink-0 rounded-full" :class="ST[s.status][2]" /><b class="font-semibold">{{ s.name }}</b><span class="tag ml-auto" :class="ST[s.status][1]">{{ ST[s.status][0] }}</span></p>
          <p class="m-0 mt-1.5 text-[13px] break-words text-ink-2">{{ summary(s) }}</p>
          <p class="m-0 mt-1 text-xs text-mute">{{ s.checked_at ? `检查于 ${formatTime(s.checked_at)}` : '还没有检查记录' }}</p>
        </li>
      </ul>

      <section class="card mt-3.5">
        <div class="card-hd"><h2>备份</h2><span class="tag" :class="ST[backup.status][1]">{{ ST[backup.status][0] }}</span></div>
        <div class="card-bd">
          <p v-if="!backup.dir_visible" class="m-0 text-[13px] text-mute">看不到备份目录，备份状态未知</p>
          <ul v-else class="m-0 grid list-none grid-cols-2 gap-2.5 p-0 sm:grid-cols-4">
            <li class="rounded-lg bg-subtle px-3 py-2"><p class="m-0 text-xs text-mute">上次每日备份</p><b class="text-[15px]">{{ backup.last_at ? formatTime(backup.last_at) : '未知' }}</b></li>
            <li class="rounded-lg bg-subtle px-3 py-2"><p class="m-0 text-xs text-mute">大小</p><b class="text-[15px] tabular-nums">{{ mb(backup.last_size_bytes) }}</b></li>
            <li class="rounded-lg px-3 py-2" :class="backup.last_ok === false ? 'bg-bad-soft' : 'bg-subtle'"><p class="m-0 text-xs" :class="backup.last_ok === false ? 'text-bad' : 'text-mute'">是否完好</p><b class="text-[15px]">{{ backup.last_ok == null ? '未知' : yn(backup.last_ok) }}</b></li>
            <li class="rounded-lg bg-subtle px-3 py-2"><p class="m-0 text-xs text-mute">下次预计</p><b class="text-[15px]">{{ backup.next_expected_at ? formatTime(backup.next_expected_at) : '未知' }}</b></li>
          </ul>
          <div v-if="backup.history.length" class="mt-3 overflow-x-auto">
            <table class="tbl">
              <thead><tr><th>时间</th><th>类型</th><th class="text-right">大小</th><th>状态</th></tr></thead>
              <tbody><tr v-for="h in backup.history" :key="h.name"><td class="text-xs whitespace-nowrap">{{ formatTime(h.at) }}</td><td>{{ h.note }}</td><td class="text-right tabular-nums">{{ mb(h.size_bytes) }}</td><td><span class="tag" :class="h.ok ? 'tag-ok' : 'tag-bad'">{{ h.ok ? '完好' : '损坏' }}</span></td></tr></tbody>
            </table>
          </div>
        </div>
      </section>

      <section class="card mt-3.5">
        <div class="card-hd"><h2>小程序配置</h2><span class="tag" :class="mini.configured ? 'tag-ok' : 'tag-gray'">{{ mini.configured ? '已配置' : '未配置' }}</span></div>
        <dl class="card-bd m-0 grid grid-cols-[110px_1fr] gap-x-3 gap-y-2 text-[13px]">
          <dt class="text-mute">AppID</dt><dd class="m-0 font-mono">{{ mini.appid || '未配置' }}</dd>
          <dt class="text-mute">Secret</dt><dd class="m-0">{{ mini.secret_configured ? '已配置（不显示）' : '未配置' }}</dd>
          <dt class="text-mute">运行环境</dt><dd class="m-0">{{ mini.env_version }}</dd>
          <dt class="text-mute">扫码登录</dt><dd class="m-0">{{ mini.wx_qr_enabled ? '已开启' : '未开启' }}</dd>
          <dt class="text-mute">订阅消息模板</dt><dd class="m-0">{{ tpl.length ? tpl.map((t) => `${t.name}${t.configured ? '' : '（未配置）'}`).join('、') : '未配置' }}</dd>
          <dt class="text-mute">提审模式</dt><dd class="m-0 text-mute">{{ mini.review_mode == null ? '未知' : mini.review_mode ? '开启' : '关闭' }}</dd>
        </dl>
      </section>
    </template>
  </div>
</template>
