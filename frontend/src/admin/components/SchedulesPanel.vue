<script setup>
import { ref } from 'vue'
import { api, formatTime, isCancelled } from '../../api'
import { toast } from '../../composables/toast'
import { onActionError } from '../composables/handled'
import { askReason } from '../composables/reason'
import { can } from '../composables/usePermissions'
import { callVerified } from '../composables/verify'

// 定时任务：每日采集、每日上新与版本提醒、数据库备份（服务器任务，只读）；可以手动执行、暂停、恢复
const items = ref(null)
const busy = ref('')
const canWrite = can('resources', 'w')
const LAST = { ok: ['成功', 'tag-ok'], failed: ['失败', 'tag-bad'], running: ['进行中', 'tag-blue'] }

async function load() {
  try {
    items.value = (await api('/api/admin/schedules')).items
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  }
}
load()
const dur = (ms) => (ms == null ? '未知' : ms >= 60000 ? `${Math.round(ms / 60000)} 分钟` : `${Math.round(ms / 1000)} 秒`)

async function run(s) {
  const reason = await askReason({ title: `现在执行「${s.name}」`, impact: '会立即开始执行一次，不影响之后按时间的执行', templates: ['手动补跑', '排查问题'], okText: '执行' })
  if (reason === null) return
  busy.value = s.key
  try {
    await api(`/api/admin/schedules/${s.key}/run`, { method: 'POST', body: { reason } })
    toast('已开始执行', 'success')
    await load()
  } catch (e) {
    if (e?.code === 'already_running') toast('正在执行中', 'error')
    else await onActionError(e, load)
  } finally {
    busy.value = ''
  }
}
async function toggle(s) {
  const pause = !s.paused
  const reason = await askReason({ title: `${pause ? '暂停' : '恢复'}「${s.name}」`, impact: pause ? '暂停后不会再按时间自动执行，直到恢复；超过 24 小时会告警；需要先验证你的邮箱' : '恢复后按原来的时间自动执行；需要先验证你的邮箱', templates: pause ? ['排查问题', '源站维护'] : ['问题已处理'], danger: pause, okText: pause ? '暂停' : '恢复' })
  if (reason === null) return
  busy.value = s.key
  try {
    await callVerified(`/api/admin/schedules/${s.key}/${pause ? 'pause' : 'resume'}`, { method: 'POST', body: { reason } }, { action: 'schedule', title: `${pause ? '暂停' : '恢复'}${s.name}` })
    toast(pause ? '已暂停' : '已恢复', 'success')
    await load()
  } catch (e) {
    await onActionError(e, load)
  } finally {
    busy.value = ''
  }
}
</script>

<template>
  <div>
    <div v-if="!items" class="skeleton mt-3 h-60" />
    <ul v-else class="m-0 mt-3 grid list-none gap-3.5 p-0 lg:grid-cols-3">
      <li v-for="s in items" :key="s.key" class="card flex flex-col px-[18px] py-3.5">
        <p class="m-0 flex items-center gap-2"><b class="font-semibold">{{ s.name }}</b><span v-if="s.paused" class="tag tag-warn ml-auto">已暂停</span><span v-else-if="s.running" class="tag tag-blue ml-auto">执行中</span><span v-else-if="!s.enabled" class="tag tag-gray ml-auto">未启用</span><span v-else class="tag tag-ok ml-auto">已启用</span></p>
        <p class="m-0 mt-1 text-[13px] text-ink-2">{{ s.cron }}</p>
        <dl class="m-0 mt-3 grid grid-cols-[84px_1fr] gap-x-2 gap-y-1.5 text-[13px]">
          <dt class="text-mute">下次执行</dt><dd class="m-0">{{ s.next_run_at ? formatTime(s.next_run_at) : s.paused ? '已暂停' : '未知' }}</dd>
          <dt class="text-mute">上次执行</dt>
          <dd class="m-0">
            <template v-if="s.last_run"><span class="tag mr-1.5" :class="LAST[s.last_run.status]?.[1] || 'tag-gray'">{{ LAST[s.last_run.status]?.[0] || s.last_run.status }}</span><span class="text-xs text-mute">{{ formatTime(s.last_run.at) }} · 用时 {{ dur(s.last_run.duration_ms) }}</span><span v-if="s.last_run.summary" class="block text-xs break-words text-ink-2">{{ s.last_run.summary }}</span></template>
            <template v-else>未知</template>
          </dd>
          <template v-if="s.paused"><dt class="text-mute">暂停</dt><dd class="m-0 text-xs text-mute">{{ s.paused_by?.label || '' }} 于 {{ formatTime(s.paused_at) }}</dd></template>
        </dl>
        <p v-if="!s.controllable" class="m-0 mt-auto pt-3 text-xs text-mute">服务器上的定时任务，这里只能查看</p>
        <div v-else-if="canWrite" class="mt-auto flex gap-2 pt-3">
          <button class="btn btn-sm" :disabled="!!busy || s.running || s.paused" @click="run(s)">立即执行</button>
          <button class="btn btn-sm" :class="s.paused ? '' : 'btn-danger'" :disabled="!!busy" @click="toggle(s)">{{ s.paused ? '恢复' : '暂停' }}</button>
        </div>
      </li>
    </ul>
  </div>
</template>
