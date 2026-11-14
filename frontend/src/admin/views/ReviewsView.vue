<script setup>
import AiTag from '../../components/AiTag.vue'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api, formatStars, formatTime, isCancelled, timeAgo } from '../../api'
import Icon from '../../components/Icon.vue'
import { confirmDialog } from '../../composables/dialog'
import { toast } from '../../composables/toast'
import ASelect from '../components/ASelect.vue'
import { onActionError } from '../composables/handled'
import { askReason } from '../composables/reason'
import { reasonTemplates } from '../composables/useReasonTemplates'
import { REASONS } from '../reasons'

// 审核：AI 审核权限（最大 / 中等 / 关闭）、待你审核、上线日志（AI 通过的可撤回）
const emit = defineEmits(['changed'])
const settings = ref(null)
const pending = ref(null)
const log = ref(null)
const logPage = ref(1)
const logFilter = ref({ reviewer: '', decision: '' })
const busy = ref(new Set())
const open = ref(new Set())
let timer

const MODE_DESC = {
  max: 'AI 全权审核：通过的直接上线、不通过的直接驳回，你事后在上线日志里查看，随时可以撤回。',
  medium: 'AI 有把握的直接处理；拿不准的转给你，你点「通过」才上线。',
  off: 'AI 只给意见和理由，全部由你审核。',
}
const DECISION = {
  approve: ['通过上线', 'tag-ok'],
  reject: ['驳回', 'tag-bad'],
  unsure: ['转交管理员', 'tag-warn'],
  revoke: ['撤回下线', 'tag-gray'],
  restore: ['重新上线', 'tag-ok'],
}
const THRESHOLDS = [0.6, 0.7, 0.8, 0.9]
const reviewerOptions = [{ value: '', label: '全部审核人' }, { value: 'ai', label: 'AI' }, { value: 'admin', label: '管理员' }]
const decisionOptions = [{ value: '', label: '全部结论' }, ...Object.entries(DECISION).map(([k, v]) => ({ value: k, label: v[0] }))]
const waiting = computed(() => (pending.value || []).filter((x) => x.review_state === 'admin'))
const running = computed(() => (pending.value || []).filter((x) => x.review_state !== 'admin'))

function fail(e) {
  if (!isCancelled(e)) toast(e.message, 'error')
}

async function loadAll() {
  clearTimeout(timer)
  try {
    const [s, p] = await Promise.all([api('/api/admin/reviews/settings'), api('/api/admin/reviews/pending')])
    settings.value = s
    pending.value = p
    if (logPage.value === 1) await loadLog()
  } catch (e) {
    fail(e)
  }
  // 有条目在 AI 处理中时 5 秒刷新一次，否则 20 秒
  timer = setTimeout(loadAll, running.value.length ? 5000 : 20000)
}

async function loadLog(more = false) {
  logPage.value = more ? logPage.value + 1 : 1
  try {
    const d = await api(`/api/admin/reviews/log?${new URLSearchParams({ ...logFilter.value, page: logPage.value })}`)
    log.value = more ? { ...d, items: [...log.value.items, ...d.items] } : d
  } catch (e) {
    fail(e)
  }
}

async function saveSettings(patch) {
  try {
    const body = { mode: settings.value.mode, threshold: settings.value.threshold, ...patch }
    settings.value = { ...settings.value, ...(await api('/api/admin/reviews/settings', { method: 'PUT', body })) }
    toast(`AI 审核权限：${settings.value.mode_label}${settings.value.mode === 'medium' ? `，把握低于 ${Math.round(settings.value.threshold * 100)}% 转给你` : ''}`, 'success')
  } catch (e) {
    fail(e)
  }
}

async function decide(it, decision) {
  const name = it.name || it.item_name
  let reason = ''
  if (decision === 'reject' || decision === 'revoke') {
    const reject = decision === 'reject'
    reason = await askReason({
      title: reject ? `驳回「${name}」` : `撤回「${name}」`,
      impact: reject ? '理由会展示给提交者' : '条目将下线，理由会展示给提交者',
      templates: await reasonTemplates(reject ? 'item_reject' : 'item_revoke', reject ? REASONS.itemReject : REASONS.itemRevoke),
      danger: true,
      okText: reject ? '驳回' : '撤回下线',
    })
    if (reason === null) return
  } else if (!(await confirmDialog({ title: `通过并上线「${name}」？`, message: '上线后所有人都能看到这个条目。', okText: '通过上线' }))) {
    return
  }
  const id = it.item_id || it.id
  busy.value = new Set(busy.value).add(id)
  try {
    await api(`/api/admin/items/${id}/review`, { method: 'POST', body: { decision, reason, expected_status: it.status || it.item_status } })
    toast(`「${name}」${DECISION[decision][0]}`, 'success')
    emit('changed')
    await loadAll()
    if (logPage.value > 1) await loadLog()
  } catch (e) {
    await onActionError(e, loadAll)
  } finally {
    const s = new Set(busy.value)
    s.delete(id)
    busy.value = s
  }
}

function toggle(id) {
  const s = new Set(open.value)
  s.has(id) ? s.delete(id) : s.add(id)
  open.value = s
}

function aiTag(o) {
  if (!o) return ['AI 未给意见', 'tag-gray']
  const pct = o.confidence != null ? ` ${Math.round(o.confidence * 100)}%` : ''
  return { approve: [`建议通过${pct}`, 'tag-ok'], reject: [`建议驳回${pct}`, 'tag-bad'] }[o.decision] || [`拿不准${pct}`, 'tag-warn']
}

onMounted(loadAll)
onBeforeUnmount(() => clearTimeout(timer))
</script>

<template>
  <div>
    <h1 class="m-0 text-xl font-semibold">审核</h1>
    <p class="mt-1 mb-5 text-[13px] text-mute">用户新增的 Skill 由 AI 在整理完介绍后立即审核；管理员和自动采集新增的不经过审核。</p>

    <!-- AI 审核权限 -->
    <section class="card">
      <div class="card-hd"><h2>AI 审核权限</h2><span class="tag tag-blue">AI</span></div>
      <div class="card-bd">
        <div v-if="!settings" class="skeleton h-24" />
        <template v-else>
          <div class="grid gap-2.5 md:grid-cols-3" role="radiogroup" aria-label="AI 审核权限">
            <button
              v-for="(label, k) in settings.modes"
              :key="k"
              role="radio"
              :aria-checked="settings.mode === k"
              class="rounded-lg border p-3.5 text-left transition-colors"
              :class="settings.mode === k ? 'border-primary bg-primary-soft' : 'border-line bg-white hover:border-[#cdd6e3]'"
              @click="settings.mode !== k && saveSettings({ mode: k })"
            >
              <p class="m-0 flex items-center gap-2 font-semibold" :class="{ 'text-primary': settings.mode === k }">
                <span class="grid h-4 w-4 place-items-center rounded-full border-2" :class="settings.mode === k ? 'border-primary' : 'border-[#c3cddb]'">
                  <span v-if="settings.mode === k" class="h-1.5 w-1.5 rounded-full bg-primary" />
                </span>{{ label }}<span v-if="k === 'medium'" class="text-xs font-normal text-mute">默认</span>
              </p>
              <p class="mt-1.5 mb-0 text-[12.5px] leading-relaxed text-ink-2">{{ MODE_DESC[k] }}</p>
            </button>
          </div>
          <div v-if="settings.mode === 'medium'" class="mt-3.5 flex flex-wrap items-center gap-2.5 text-[13px] text-ink-2">
            AI 把握低于
            <div class="seg">
              <button v-for="t in THRESHOLDS" :key="t" :class="{ on: Math.abs(settings.threshold - t) < 0.001 }" @click="saveSettings({ threshold: t })">{{ Math.round(t * 100) }}%</button>
            </div>
            时转交给你
          </div>
        </template>
      </div>
    </section>

    <!-- 待你审核 -->
    <section class="card mt-3.5">
      <div class="card-hd">
        <h2>待你审核</h2>
        <span v-if="waiting.length" class="tag tag-bad">{{ waiting.length }}</span>
        <span v-if="running.length" class="ml-auto flex items-center gap-1.5 text-xs text-primary">
          <Icon name="refresh" :size="13" class="animate-spin" />{{ running.length }} 个正在提炼 / AI 审核
        </span>
      </div>
      <div v-if="!pending" class="card-bd"><div class="skeleton h-28" /></div>
      <p v-else-if="!waiting.length" class="empty">没有需要你审核的条目<template v-if="running.length">（{{ running.map((x) => x.name).join('、') }} 正在 AI 审核，完成后若拿不准会出现在这里）</template></p>
      <ul v-else class="m-0 list-none p-0">
        <li v-for="it in waiting" :key="it.id" class="border-b border-line px-[18px] py-3.5 last:border-0">
          <div class="flex flex-wrap items-center gap-x-2.5 gap-y-1.5">
            <a :href="`/items/${it.id}`" target="_blank" class="font-semibold hover:text-primary">{{ it.name }}</a>
            <span class="tag" :class="aiTag(it.ai_opinion)[1]">{{ aiTag(it.ai_opinion)[0] }}</span>
            <span v-if="it.kind" class="tag tag-gray">{{ it.kind.name }}</span>
            <span v-if="it.stars" class="flex items-center gap-0.5 text-xs text-mute"><Icon name="star" :size="11" />{{ formatStars(it.stars) }}</span>
            <span class="ml-auto flex items-center gap-2">
              <button class="btn btn-sm btn-danger" :disabled="busy.has(it.id)" @click="decide(it, 'reject')"><Icon name="x" :size="14" />驳回</button>
              <button class="btn btn-sm btn-primary" :disabled="busy.has(it.id)" @click="decide(it, 'approve')"><Icon name="check" :size="14" />通过上线</button>
            </span>
          </div>
          <p class="mt-1 mb-0 text-xs text-mute">
            <a v-if="it.github_url" :href="it.github_url" target="_blank" rel="noopener" class="hover:text-primary">{{ it.repo_full_name ? it.repo_full_name + (it.sub_path ? '/' + it.sub_path : '') : it.github_url }}</a>
            · {{ it.submitter?.nickname || '—' }}<template v-if="it.submitter?.email">（{{ it.submitter.email }}）</template> · {{ timeAgo(it.collected_at) }}提交
          </p>
          <p v-if="it.ai_opinion?.reason" class="mt-2 mb-0 rounded-md bg-subtle px-3 py-2 text-[13px] text-ink-2">
            <AiTag :model="it.ai_opinion.model" class="mr-1.5 align-middle" />
            <b class="font-semibold text-ink">AI：</b>{{ it.ai_opinion.reason }}
          </p>
          <p class="mt-2 mb-0 text-[13px] text-ink-2" :class="{ 'line-clamp-2': !open.has(it.id) }">{{ it.summary || '暂无简介' }}</p>
          <button v-if="(it.summary || '').length > 80" class="mt-0.5 text-xs text-primary" @click="toggle(it.id)">{{ open.has(it.id) ? '收起' : '展开简介' }}</button>
        </li>
      </ul>
    </section>

    <!-- 上线日志 -->
    <section class="card mt-3.5">
      <div class="card-hd">
        <h2>上线日志</h2>
        <span v-if="log" class="text-xs text-mute">共 {{ log.total }} 条</span>
        <div class="ml-auto flex gap-2">
          <ASelect v-model="logFilter.reviewer" :options="reviewerOptions" label="审核人" class="w-32" @update:model-value="loadLog()" />
          <ASelect v-model="logFilter.decision" :options="decisionOptions" label="结论" class="w-32" @update:model-value="loadLog()" />
        </div>
      </div>
      <div v-if="!log" class="card-bd"><div class="skeleton h-40" /></div>
      <p v-else-if="!log.items.length" class="empty">还没有审核记录</p>
      <div v-else class="overflow-x-auto">
        <table class="tbl">
          <thead><tr><th>结论</th><th>条目</th><th class="hidden md:table-cell">审核人</th><th class="text-right">时间</th></tr></thead>
          <tbody>
            <tr v-for="r in log.items" :key="r.id">
              <td class="w-28"><span class="tag" :class="DECISION[r.decision]?.[1] || 'tag-gray'">{{ DECISION[r.decision]?.[0] || r.decision }}</span></td>
              <td>
                <a v-if="r.item_id" :href="`/items/${r.item_id}`" target="_blank" class="font-semibold hover:text-primary">{{ r.item_name }}</a>
                <b v-else class="font-semibold">{{ r.item_name }}</b>
                <span class="ml-1.5 text-xs text-mute">提交：{{ r.submitter?.nickname || '—' }}</span>
                <span v-if="r.reason" class="block text-[12.5px] text-ink-2">{{ r.reason }}</span>
              </td>
              <td class="hidden whitespace-nowrap md:table-cell">
                <template v-if="r.reviewer === 'ai'"><span class="tag tag-blue">AI</span><span v-if="r.confidence != null" class="ml-1.5 text-xs text-mute">把握 {{ Math.round(r.confidence * 100) }}%</span></template>
                <template v-else><Icon name="shield" :size="13" class="mr-1 inline text-mute" />{{ r.admin || '管理员' }}</template>
              </td>
              <td class="text-right whitespace-nowrap">
                <time class="text-xs text-mute" :title="formatTime(r.created_at)">{{ timeAgo(r.created_at) }}</time>
                <button
                  v-if="r.reviewer === 'ai' && r.decision === 'approve' && r.item_status === 'published'"
                  class="btn btn-sm btn-danger ml-2"
                  :disabled="busy.has(r.item_id)"
                  @click="decide(r, 'revoke')"
                >撤回下线</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="log && log.items.length < log.total" class="flex justify-center border-t border-line py-3">
        <button class="btn btn-sm" @click="loadLog(true)">加载更多</button>
      </div>
    </section>
  </div>
</template>
