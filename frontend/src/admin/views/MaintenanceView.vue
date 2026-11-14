<script setup>
import { computed, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { api, formatTime, isCancelled } from '../../api'
import Icon from '../../components/Icon.vue'
import { toast } from '../../composables/toast'
import ADrawer from '../components/ADrawer.vue'
import ALogItem from '../components/ALogItem.vue'
import AResultPanel from '../components/AResultPanel.vue'
import { onActionError } from '../composables/handled'
import { askReason } from '../composables/reason'
import { useDetailRoute } from '../composables/useDetailRoute'
import { can } from '../composables/usePermissions'

// 维护工具：重算评分、重算榜单、补语义向量、补缩略图和动图、清缓存；数据一致性检查与修复。执行前都能先预览，执行要填原因并留日志
const route = useRoute()
const router = useRouter()
const TABS = [['tools', '维护工具'], ['consistency', '数据一致性']]
const tab = computed(() => (route.query.tab === 'consistency' ? 'consistency' : 'tools'))
const setTab = (t) => router.replace({ query: { tab: t === 'tools' ? undefined : t } })
const canWrite = computed(() => can('maintenance', 'w'))

// ------------------------------------------------------------ 维护工具
const tools = ref(null)
const logs = ref(null)
const preview = ref({}) // key → 预览结果
const names = ref({}) // 工具和检查项的中文名（执行记录里的标签用）
const labelOf = (r) => names.value[r.target_label] || r.target_label || r.action_label
const busy = ref('')
async function loadTools() {
  try {
    const [t, l, c] = await Promise.all([api('/api/admin/maintenance'), api('/api/admin/activity?target_type=maintenance&page_size=20'), api('/api/admin/consistency')])
    tools.value = t.tools
    logs.value = l.items
    names.value = Object.fromEntries([...t.tools.map((x) => [x.key, x.name]), ...c.checks.map((x) => [x.key, x.name])])
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  }
}
async function previewTool(t) {
  busy.value = `p:${t.key}`
  try {
    preview.value = { ...preview.value, [t.key]: await api(`/api/admin/maintenance/${t.key}/run`, { method: 'POST', body: { dry_run: true, reason: '' } }) }
  } catch (e) {
    await onActionError(e)
  } finally {
    busy.value = ''
  }
}
async function runTool(t) {
  const reason = await askReason({
    title: `执行「${t.name}」？`,
    impact: preview.value[t.key]?.summary || (t.dangerous ? '会影响线上数据，建议先预览' : '执行结果会记入维护记录'),
    templates: ['定期维护', '数据异常，修复一下', '上线后例行检查'],
    danger: t.dangerous,
    okText: '执行',
  })
  if (reason === null) return
  busy.value = `r:${t.key}`
  try {
    const r = await api(`/api/admin/maintenance/${t.key}/run`, { method: 'POST', body: { dry_run: false, reason } })
    if (r.ok) toast(r.summary || '已执行', 'success')
    else toast(r.summary || '执行失败', 'error')
    preview.value = { ...preview.value, [t.key]: undefined }
    await loadTools()
    if (r.task_id) runTask.value = r.task_id
  } catch (e) {
    await onActionError(e, loadTools)
  } finally {
    busy.value = ''
  }
}
const runTask = ref('')

// ------------------------------------------------------------ 数据一致性
const checks = ref(null)
const detail = useDetailRoute('check')
const current = ref(null)
const results = ref({ open: false, title: '', rows: [] })
async function loadChecks() {
  try {
    checks.value = (await api('/api/admin/consistency')).checks
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  }
}
async function scan(c) {
  busy.value = `s:${c.key}`
  try {
    await api(`/api/admin/consistency/${c.key}/scan`, { method: 'POST', body: {} })
    await loadChecks()
    if (detail.id.value === c.key) await loadDetail(c.key)
  } catch (e) {
    await onActionError(e, loadChecks)
  } finally {
    busy.value = ''
  }
}
async function loadDetail(key) {
  try {
    const d = await api(`/api/admin/consistency/${key}`)
    if (detail.id.value === key) current.value = d
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
    detail.close()
  }
}
watch(detail.id, (k) => {
  current.value = null
  if (k) loadDetail(k)
}, { immediate: true })

async function fix(c, ids) {
  const scope = ids ? { ids } : { all: true }
  let pre
  try {
    pre = await api(`/api/admin/consistency/${c.key}/fix`, { method: 'POST', body: { ...scope, dry_run: true, reason: '' } })
  } catch (e) {
    await onActionError(e)
    return
  }
  if (!pre.count) {
    toast('没有需要修复的项了', 'info')
    await scanAfter(c)
    return
  }
  const reason = await askReason({
    title: ids ? `修复这 ${ids.length} 项？` : `修复「${c.name}」的全部不一致？`,
    impact: `将修复 ${pre.count} 项${pre.already_ok ? `（${pre.already_ok} 项已经一致，会跳过）` : ''}`,
    templates: ['数据不一致，修复', '定期检查发现问题'],
    danger: true,
    okText: '修复',
  })
  if (reason === null) return
  busy.value = `f:${c.key}`
  try {
    const r = await api(`/api/admin/consistency/${c.key}/fix`, { method: 'POST', body: { ...scope, reason, dry_run: false } })
    results.value = { open: true, title: `修复「${c.name}」`, rows: r.results }
    await scanAfter(c)
  } catch (e) {
    await onActionError(e, () => scanAfter(c))
  } finally {
    busy.value = ''
  }
}
async function scanAfter(c) {
  await loadChecks()
  if (detail.id.value === c.key) await loadDetail(c.key)
}

watch(tab, (t) => (t === 'tools' ? loadTools() : loadChecks()), { immediate: true })

const STATUS = { ok: ['一致', 'tag-ok'], warn: ['有不一致', 'tag-warn'], unknown: ['未检查', 'tag-gray'] }
const kv = (o) => Object.entries(o || {})
</script>

<template>
  <div>
    <div class="flex flex-wrap items-center gap-3">
      <h1 class="m-0 text-xl font-semibold">维护工具</h1>
      <div class="seg ml-auto"><button v-for="t in TABS" :key="t[0]" :class="{ on: tab === t[0] }" @click="setTab(t[0])">{{ t[1] }}</button></div>
    </div>

    <!-- 工具 -->
    <template v-if="tab === 'tools'">
      <div v-if="!tools" class="mt-5 grid gap-3.5 md:grid-cols-2"><div class="skeleton h-40" /><div class="skeleton h-40" /></div>
      <ul v-else class="m-0 mt-5 grid list-none gap-3.5 p-0 md:grid-cols-2">
        <li v-for="t in tools" :key="t.key" class="card flex flex-col p-[18px]">
          <div class="flex items-center gap-2"><h2 class="m-0 text-[15px] font-semibold">{{ t.name }}</h2><span v-if="t.dangerous" class="tag tag-warn">会影响线上</span></div>
          <p v-if="t.last_run" class="m-0 mt-2 text-[13px] text-ink-2">
            上次执行 {{ formatTime(t.last_run.at) }} · {{ t.last_run.by?.label }}<span class="tag ml-1.5" :class="t.last_run.ok ? 'tag-ok' : 'tag-bad'">{{ t.last_run.ok ? '成功' : '失败' }}</span>
            <span class="block break-words text-xs text-mute">{{ t.last_run.summary }}<template v-if="t.last_run.reason"> · 原因：{{ t.last_run.reason }}</template></span>
          </p>
          <p v-else class="m-0 mt-2 text-[13px] text-mute">还没有执行过</p>
          <p v-if="preview[t.key]" class="m-0 mt-3 rounded-lg px-3 py-2 text-[13px]" :class="preview[t.key].ok ? 'bg-primary-soft text-primary' : 'bg-bad-soft text-bad'"><b>预览：</b>{{ preview[t.key].summary }}</p>
          <div class="mt-auto flex flex-wrap gap-2 pt-4">
            <button class="btn" :disabled="!!busy" @click="previewTool(t)"><Icon name="eye" :size="14" />{{ busy === `p:${t.key}` ? '预览中…' : '预览' }}</button>
            <button v-if="canWrite" class="btn" :class="t.dangerous ? 'btn-danger' : 'btn-primary'" :disabled="!!busy" @click="runTool(t)"><Icon name="play" :size="14" />{{ busy === `r:${t.key}` ? '执行中…' : '执行' }}</button>
          </div>
        </li>
      </ul>
      <p v-if="runTask" class="m-0 mt-3 flex items-center gap-2 rounded-lg bg-primary-soft px-3.5 py-2.5 text-[13px] text-primary">已转为后台任务 {{ runTask }}<RouterLink :to="{ path: '/ingest-tasks', query: { id: runTask } }" class="font-medium underline">查看进度</RouterLink><button class="ml-auto underline" @click="runTask = ''">知道了</button></p>

      <section class="card mt-3.5">
        <div class="card-hd"><h2>执行记录</h2></div>
        <div v-if="!logs" class="card-bd"><div class="skeleton h-24" /></div>
        <p v-else-if="!logs.length" class="empty">还没有执行记录</p>
        <ul v-else class="m-0 list-none p-0">
          <li v-for="r in logs" :key="r.id" class="border-b border-dashed border-line px-[18px] py-2.5 text-[13px] last:border-0">
            <span class="mb-1 flex flex-wrap items-center gap-1.5"><span class="tag tag-blue">{{ labelOf(r) }}</span><span v-if="r.result === 'failed'" class="tag tag-bad">失败</span><span class="text-xs text-ink-2">{{ r.user?.label || '系统' }}</span><span class="text-xs text-mute">{{ formatTime(r.created_at) }}</span></span>
            <ALogItem :row="r" compact />
          </li>
        </ul>
      </section>
    </template>

    <!-- 数据一致性 -->
    <template v-else>
      <section class="card mt-5">
        <div v-if="!checks" class="card-bd"><div class="skeleton h-40" /></div>
        <ul v-else class="m-0 list-none p-0">
          <li v-for="c in checks" :key="c.key" class="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-line px-[18px] py-3 last:border-0">
            <div class="min-w-0 flex-1 basis-56">
              <b class="font-medium">{{ c.name }}</b>
              <span class="tag ml-2" :class="STATUS[c.status][1]">{{ STATUS[c.status][0] }}<template v-if="c.status === 'warn'"> {{ c.mismatches }} 处</template></span>
              <span class="block text-xs text-mute">{{ c.checked_at ? `上次检查 ${formatTime(c.checked_at)}` : '还没有检查过' }}</span>
            </div>
            <span class="flex flex-wrap gap-2">
              <button class="btn btn-sm" :disabled="!!busy" @click="scan(c)"><Icon name="refresh" :size="14" :class="{ 'animate-spin': busy === `s:${c.key}` }" />扫描</button>
              <button v-if="c.mismatches" class="btn btn-sm" @click="detail.open(c.key)">查看明细</button>
              <button v-if="c.mismatches && canWrite" class="btn btn-sm btn-danger" :disabled="!!busy" @click="fix(c)">全部修复</button>
            </span>
          </li>
        </ul>
      </section>
    </template>

    <ADrawer :open="!!detail.id.value" label="不一致明细" :width="640" @close="detail.close()">
      <template #header>
        <p v-if="!current" class="m-0 text-mute">加载中…</p>
        <div v-else>
          <p class="m-0 font-semibold">{{ current.name }}<span class="tag ml-2" :class="STATUS[current.status][1]">{{ STATUS[current.status][0] }}</span></p>
          <p class="m-0 truncate text-xs text-mute">{{ current.mismatches }} 处不一致 · 显示前 {{ current.limit }} 条</p>
        </div>
      </template>
      <div v-if="!current" class="skeleton h-60" />
      <p v-else-if="!current.items.length" class="empty">没有不一致的记录</p>
      <ul v-else class="m-0 list-none p-0">
        <li v-for="i in current.items" :key="i.id" class="border-b border-dashed border-line py-3 text-[13px] last:border-0">
          <span class="flex items-center gap-2"><b class="min-w-0 flex-1 break-words font-medium">{{ i.label }}</b><button v-if="canWrite" class="btn btn-sm shrink-0" :disabled="!!busy" @click="fix(current, [i.id])">修复</button></span>
          <span class="mt-1.5 grid grid-cols-[56px_1fr] gap-x-2 gap-y-0.5 text-xs">
            <span class="text-mute">记录的</span><span class="break-all text-ink-2"><template v-for="[k, v] in kv(i.stored)" :key="k"><span class="mr-2">{{ k }}：{{ v }}</span></template></span>
            <span class="text-mute">实际</span><span class="break-all text-ink"><template v-for="[k, v] in kv(i.actual)" :key="k"><span class="mr-2">{{ k }}：{{ v }}</span></template></span>
          </span>
        </li>
      </ul>
      <template v-if="current && current.mismatches && canWrite" #footer>
        <div class="flex items-center gap-2"><button class="btn btn-danger ml-auto" :disabled="!!busy" @click="fix(current)">全部修复（{{ current.mismatches }}）</button></div>
      </template>
    </ADrawer>
    <AResultPanel :open="results.open" :title="results.title" :results="results.rows" @close="results.open = false" />
  </div>
</template>
