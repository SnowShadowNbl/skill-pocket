<script setup>
import { onMounted, ref } from 'vue'
import { api, formatTime, isCancelled, timeAgo } from '../../api'
import Icon from '../../components/Icon.vue'
import { confirmDialog } from '../../composables/dialog'
import { toast } from '../../composables/toast'

// 失效巡检：每天 03:30 检查收录条目的 GitHub 原地址；失效的逻辑下线（不删数据），恢复后自动上线
const emit = defineEmits(['changed'])
const data = ref(null)
const running = ref(false)
const STATUS = { ok: ['完成', 'tag-ok'], running: ['进行中', 'tag-blue'], partial: ['部分完成', 'tag-warn'] }

async function load() {
  try {
    data.value = await api('/api/admin/liveness')
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  }
}

async function runNow() {
  if (!(await confirmDialog({ title: '立即执行一次失效巡检？', message: '会检查全部收录条目的 GitHub 原地址，大约需要 1~3 分钟。', okText: '开始巡检' }))) return
  running.value = true
  try {
    await api('/api/admin/liveness/run', { method: 'POST' })
    toast('已开始巡检，完成后会自动刷新', 'success')
    setTimeout(async () => {
      await load()
      running.value = false
    }, 20000)
  } catch (e) {
    running.value = false
    if (!isCancelled(e)) toast(e.message, 'error')
  }
}

async function restore(it) {
  if (!(await confirmDialog({ title: `把「${it.name}」重新上线？`, message: '如果原地址仍然失效，下一次巡检会再次把它下线。', okText: '重新上线' }))) return
  try {
    await api(`/api/admin/items/${it.id}/review`, { method: 'POST', body: { decision: 'restore', reason: '管理员手动重新上线' } })
    toast(`「${it.name}」已重新上线`, 'success')
    emit('changed')
    load()
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div class="flex flex-wrap items-end gap-3">
      <div>
        <h1 class="m-0 text-xl font-semibold">失效巡检</h1>
        <p class="mt-1 mb-0 text-[13px] text-mute">每天 03:30 自动检查：仓库被删除 / 封禁 / 清空，或 Skill 目录被删除，就逻辑下线（不删数据）；已归档不算失效；原地址恢复后自动重新上线。</p>
      </div>
      <button class="btn btn-primary ml-auto" :disabled="running" @click="runNow">
        <Icon :name="running ? 'refresh' : 'play'" :size="15" :class="{ 'animate-spin': running }" />{{ running ? '巡检中…' : '立即巡检' }}
      </button>
    </div>

    <section class="card mt-5">
      <div class="card-hd"><h2>巡检记录</h2></div>
      <div v-if="!data" class="card-bd"><div class="skeleton h-32" /></div>
      <p v-else-if="!data.runs.length" class="empty">还没有巡检记录，今晚 03:30 会自动执行第一次</p>
      <table v-else class="tbl">
        <thead><tr><th>时间</th><th>检查</th><th>新下线</th><th>恢复</th><th class="hidden md:table-cell">说明</th><th class="text-right">状态</th></tr></thead>
        <tbody>
          <tr v-for="r in data.runs" :key="r.id" class="align-top">
            <td class="whitespace-nowrap tabular-nums">{{ formatTime(r.started_at) }}</td>
            <td class="tabular-nums">{{ r.checked }}</td>
            <td class="tabular-nums" :class="r.went_offline ? 'font-semibold text-bad' : 'text-mute'">{{ r.went_offline }}</td>
            <td class="tabular-nums" :class="r.restored ? 'font-semibold text-ok' : 'text-mute'">{{ r.restored }}</td>
            <td class="hidden text-[12.5px] text-ink-2 md:table-cell">
              <span v-if="r.errors" class="block text-warn">查询失败 {{ r.errors }}（下次重试）</span>
              <span v-for="c in r.changes" :key="c.item_id + c.change" class="block">
                <span :class="c.change === 'offline' ? 'text-bad' : 'text-ok'">{{ c.change === 'offline' ? '下线' : '恢复' }}</span>「{{ c.name }}」<span v-if="c.reason" class="text-mute">{{ c.reason }}</span>
              </span>
              <span v-if="!r.errors && !r.changes.length" class="text-mute">无变化</span>
            </td>
            <td class="text-right"><span class="tag" :class="STATUS[r.status]?.[1] || 'tag-gray'">{{ STATUS[r.status]?.[0] || r.status }}</span></td>
          </tr>
        </tbody>
      </table>
    </section>

    <section class="card mt-3.5">
      <div class="card-hd"><h2>已下线的条目</h2><span v-if="data" class="text-xs text-mute">{{ data.offline.length }}</span></div>
      <p v-if="data && !data.offline.length" class="empty">没有已下线的条目</p>
      <table v-else-if="data" class="tbl">
        <tbody>
          <tr v-for="it in data.offline" :key="it.id">
            <td><b class="font-semibold">{{ it.name }}</b><a :href="`https://github.com/${it.repo}`" target="_blank" rel="noopener" class="block text-xs text-mute hover:text-primary">{{ it.repo }}</a></td>
            <td class="text-[12.5px] text-bad">{{ it.offline_reason }}</td>
            <td class="hidden text-xs whitespace-nowrap text-mute md:table-cell">{{ timeAgo(it.offline_at) }}</td>
            <td class="text-right"><button class="btn btn-sm" @click="restore(it)">重新上线</button></td>
          </tr>
        </tbody>
      </table>
    </section>
  </div>
</template>
