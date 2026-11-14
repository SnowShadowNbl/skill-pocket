<script setup>
import { computed, ref } from 'vue'
import { api, isCancelled } from '../../api'
import Icon from '../../components/Icon.vue'
import { toast } from '../../composables/toast'
import { onActionError } from '../composables/handled'
import { askReason } from '../composables/reason'
import { can } from '../composables/usePermissions'
import { callVerified } from '../composables/verify'

// 存储与清理：数据库和媒体文件占用、磁盘剩余；日志 / 事件 / 访客 / 操作日志的保留天数（改动要二次验证）；手动清理（先预览再执行）
const d = ref(null)
const draft = ref({})
const preview = ref({})
const busy = ref('')
const canWrite = computed(() => can('resources', 'w'))
const RET = [['activity_days', '操作日志'], ['events_days', '行为事件'], ['logs_days', '入库日志'], ['visitors_days', '访客记录']]

async function load() {
  try {
    d.value = await api('/api/admin/storage')
    draft.value = { ...d.value.retention }
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  }
}
load()

const bytes = (n) => (n == null ? '未知' : n >= 1073741824 ? `${(n / 1073741824).toFixed(2)} GB` : n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${(n / 1024).toFixed(0)} KB`)
const mediaRows = computed(() => (d.value ? [['封面', d.value.media.covers_bytes], ['缩略图', d.value.media.thumb_bytes], ['动图', d.value.media.anim_bytes], ['用户上传的截图', d.value.media.uploads_bytes], ['其他', d.value.media.other_bytes]] : []))
const mediaTotal = computed(() => mediaRows.value.reduce((n, r) => n + (r[1] || 0), 0) || 1)
const dirty = computed(() => d.value && RET.some(([k]) => Number(draft.value[k]) !== d.value.retention[k]))
const bad = computed(() => d.value && RET.some(([k]) => !(Number(draft.value[k]) >= d.value.retention_range[0] && Number(draft.value[k]) <= d.value.retention_range[1])))

async function saveRetention() {
  const reason = await askReason({ title: '修改数据保留天数', impact: '新的天数会用于自动清理和手动清理；需要先验证你的邮箱', templates: ['调整保留策略', '磁盘空间紧张，缩短保留'], danger: true, okText: '保存' })
  if (reason === null) return
  busy.value = 'ret'
  try {
    const body = { reason, ...Object.fromEntries(RET.map(([k]) => [k, Number(draft.value[k])])) }
    const r = await callVerified('/api/admin/storage/retention', { method: 'PUT', body }, { action: 'retention', title: '修改数据保留天数' })
    d.value.retention = r.retention
    toast('已保存', 'success')
  } catch (e) {
    await onActionError(e)
  } finally {
    busy.value = ''
  }
}
async function previewClean(key) {
  busy.value = `p:${key}`
  try {
    preview.value = { ...preview.value, [key]: await api('/api/admin/storage/cleanup', { method: 'POST', body: { target: key, dry_run: true, reason: '' } }) }
  } catch (e) {
    await onActionError(e)
  } finally {
    busy.value = ''
  }
}
async function runClean(key, name) {
  const reason = await askReason({ title: `清理「${name}」`, impact: preview.value[key]?.summary || '删除后不能恢复，建议先预览', templates: ['定期清理', '磁盘空间紧张'], danger: true, okText: '清理' })
  if (reason === null) return
  busy.value = `r:${key}`
  try {
    const r = await api('/api/admin/storage/cleanup', { method: 'POST', body: { target: key, dry_run: false, reason } })
    toast(r.summary || '已清理', 'success')
    preview.value = { ...preview.value, [key]: undefined }
    await load()
  } catch (e) {
    await onActionError(e)
  } finally {
    busy.value = ''
  }
}
</script>

<template>
  <div>
    <div v-if="!d" class="skeleton mt-3 h-60" />
    <template v-else>
      <ul class="m-0 mt-3 grid list-none grid-cols-2 gap-3.5 p-0 lg:grid-cols-4">
        <li class="card px-[18px] py-3.5"><p class="m-0 text-[13px] text-mute">数据库</p><b class="mt-1 block text-2xl tabular-nums">{{ bytes(d.db.size_bytes) }}</b></li>
        <li class="card px-[18px] py-3.5"><p class="m-0 text-[13px] text-mute">媒体文件</p><b class="mt-1 block text-2xl tabular-nums">{{ bytes(mediaTotal) }}</b></li>
        <li class="card px-[18px] py-3.5"><p class="m-0 text-[13px] text-mute">磁盘剩余</p><b class="mt-1 block text-2xl tabular-nums">{{ bytes(d.disk.free_bytes) }}</b></li>
        <li class="card px-[18px] py-3.5" :class="d.disk.used_pct >= 80 ? 'border-warn/50 bg-warn-soft' : ''"><p class="m-0 text-[13px]" :class="d.disk.used_pct >= 80 ? 'text-warn' : 'text-mute'">磁盘已用</p><b class="mt-1 block text-2xl tabular-nums" :class="{ 'text-warn': d.disk.used_pct >= 80 }">{{ d.disk.used_pct }}%</b></li>
      </ul>

      <div class="mt-3.5 grid gap-3.5 lg:grid-cols-2">
        <section class="card">
          <div class="card-hd"><h2>媒体文件</h2></div>
          <ul class="m-0 list-none p-0">
            <li v-for="[name, n] in mediaRows" :key="name" class="px-[18px] py-2.5">
              <span class="flex text-[13px]"><span>{{ name }}</span><b class="ml-auto tabular-nums">{{ bytes(n) }}</b></span>
              <span class="mt-1.5 block h-1.5 overflow-hidden rounded-full bg-[#eef3fa]"><span class="block h-full rounded-full bg-primary" :style="{ width: `${Math.max(1, ((n || 0) / mediaTotal) * 100)}%` }" /></span>
            </li>
          </ul>
        </section>
        <section class="card">
          <div class="card-hd"><h2>数据表</h2></div>
          <div class="max-h-72 overflow-y-auto">
            <table class="tbl">
              <thead><tr><th>表</th><th class="text-right">行数</th><th class="text-right">大小</th></tr></thead>
              <tbody><tr v-for="t in d.db.tables" :key="t.name"><td class="font-mono text-xs">{{ t.name }}</td><td class="text-right tabular-nums">{{ t.rows.toLocaleString() }}</td><td class="text-right tabular-nums text-mute">{{ bytes(t.size_bytes) }}</td></tr></tbody>
            </table>
          </div>
        </section>
      </div>

      <section class="card mt-3.5">
        <div class="card-hd"><h2>保留天数</h2><span class="text-xs text-mute">{{ d.retention_range[0] }}–{{ d.retention_range[1] }} 天</span></div>
        <form class="card-bd grid gap-3 sm:grid-cols-2 lg:grid-cols-[repeat(4,1fr)_auto]" @submit.prevent="saveRetention">
          <label v-for="[k, name] in RET" :key="k" class="block text-xs text-mute">{{ name }}<input v-model="draft[k]" type="number" class="input mt-1 tabular-nums" :min="d.retention_range[0]" :max="d.retention_range[1]" :disabled="!canWrite" :aria-label="`${name}保留天数`" /></label>
          <button v-if="canWrite" class="btn btn-primary self-end" :disabled="!dirty || bad || busy === 'ret'">保存</button>
        </form>
      </section>

      <section class="card mt-3.5">
        <div class="card-hd"><h2>清理</h2></div>
        <ul class="m-0 list-none p-0">
          <li v-for="(name, key) in d.cleanup_targets" :key="key" class="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b border-line px-[18px] py-3 last:border-0">
            <div class="min-w-0 flex-1 basis-52">
              <b class="font-medium">{{ name }}</b>
              <span v-if="preview[key]" class="mt-0.5 block text-[13px] text-primary">{{ preview[key].summary }}<template v-if="preview[key].freed_bytes != null">（约释放 {{ bytes(preview[key].freed_bytes) }}）</template></span>
            </div>
            <span class="flex gap-2">
              <button class="btn btn-sm" :disabled="!!busy" @click="previewClean(key)"><Icon name="eye" :size="14" />{{ busy === `p:${key}` ? '预览中…' : '预览' }}</button>
              <button v-if="canWrite" class="btn btn-sm btn-danger" :disabled="!!busy || (preview[key] && !preview[key].rows)" @click="runClean(key, name)">清理</button>
            </span>
          </li>
        </ul>
      </section>
    </template>
  </div>
</template>
