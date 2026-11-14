<script setup>
import { computed, ref, watch } from 'vue'
import { api, formatTime, isCancelled } from '../../api'
import { toast } from '../../composables/toast'
import { askReason } from '../composables/reason'
import { can } from '../composables/usePermissions'
import { TAG_COLOR, loadTags, tagState } from '../composables/useTags'
import ADrawer from './ADrawer.vue'
import ATable from './ATable.vue'

// 小范围公告：先存草稿，按标签 / 注册渠道选对象，预览人数和样例，确认后发到用户的铃铛；发送后看已读率
const data = ref(null)
const status = ref('')
const page = ref(1)
const canWrite = computed(() => can('operations', 'w'))
const TABS = [['', '全部'], ['draft', '草稿'], ['sent', '已发送']]
const CHANNELS = [['web-pc', 'PC 网页'], ['web-mobile', '手机网页'], ['miniprogram', '小程序'], ['unknown', '未知']]
const columns = [
  { key: 'title', label: '公告', mobile: 'title' },
  { key: 'audience', label: '对象', hideBelow: 'md', mobile: 'sub' },
  { key: 'status', label: '状态', mobile: 'meta' },
  { key: 'read', label: '已读', mobile: 'meta' },
  { key: 'actions', label: '', align: 'right', mobile: 'action' },
]
loadTags().catch(() => {})

async function load(more = false) {
  page.value = more ? page.value + 1 : 1
  try {
    const d = await api(`/api/admin/announcements?status=${status.value}&page=${page.value}`)
    data.value = more ? { ...d, items: [...data.value.items, ...d.items] } : d
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  }
}
watch(status, () => load(), { immediate: true })

// ---- 编辑 / 预览 / 发送
const open = ref(false)
const form = ref({ id: null, title: '', text: '', link: '', all: true, tag_ids: [], channels: [] })
const view = ref(null) // 已发送的公告只读查看
const preview = ref(null)
const busy = ref('')
const readonly = computed(() => !!view.value)

function newOne() {
  form.value = { id: null, title: '', text: '', link: '', all: true, tag_ids: [], channels: [] }
  view.value = null
  preview.value = null
  open.value = true
}
function openRow(a) {
  form.value = { id: a.id, title: a.title, text: a.text, link: a.link || '', all: !!a.audience.all, tag_ids: [...(a.audience.tag_ids || [])], channels: [...(a.audience.channels || [])] }
  view.value = a.status === 'sent' ? a : null
  preview.value = null
  open.value = true
}
const toggle = (key, v) => {
  const s = new Set(form.value[key])
  if (s.has(v)) s.delete(v)
  else s.add(v)
  form.value[key] = [...s]
  preview.value = null
}
const body = () => ({ title: form.value.title.trim(), text: form.value.text.trim(), link: form.value.link.trim(), audience: { all: form.value.all, tag_ids: form.value.all ? [] : form.value.tag_ids, channels: form.value.all ? [] : form.value.channels } })
const valid = computed(() => form.value.title.trim() && form.value.text.trim() && (form.value.all || form.value.tag_ids.length || form.value.channels.length))

async function save() {
  busy.value = 'save'
  try {
    const f = form.value
    const r = await api(f.id ? `/api/admin/announcements/${f.id}` : '/api/admin/announcements', { method: f.id ? 'PUT' : 'POST', body: body() })
    form.value.id = r.id
    toast('草稿已保存', 'success')
    await load()
    return true
  } catch (e) {
    toast(e.code === 'bad_link' ? '链接只能是站内路径，例如 /categories' : e.code === 'already_handled' ? '这条公告已经发送，不能再改' : e.message, 'error')
    return false
  } finally {
    busy.value = ''
  }
}
async function doPreview() {
  if (!(await save())) return
  busy.value = 'preview'
  try {
    preview.value = await api(`/api/admin/announcements/${form.value.id}/preview`, { method: 'POST' })
  } catch (e) {
    toast(e.message, 'error')
  } finally {
    busy.value = ''
  }
}
async function send() {
  const p = preview.value
  const reason = await askReason({ title: `发送公告「${form.value.title}」`, impact: `将发给 ${p.count} 位用户，发出后不能撤回`, templates: ['新功能通知', '内测邀请', '活动通知'], danger: true, okText: '发送' })
  if (reason === null) return
  busy.value = 'send'
  try {
    await api(`/api/admin/announcements/${form.value.id}/send`, { method: 'POST', body: { reason, expected_count: p.count } })
    toast(`已发送给 ${p.count} 位用户`, 'success')
    open.value = false
    await load()
  } catch (e) {
    if (e.code === 'count_changed') {
      toast('人数有变化，请重新预览确认', 'error')
      await doPreview()
    } else toast(e.code === 'empty_audience' ? '没有符合条件的用户' : e.code === 'too_many' ? '人数太多，请缩小范围' : e.message, 'error')
  } finally {
    busy.value = ''
  }
}
async function remove(a) {
  const reason = await askReason({ title: `删除草稿「${a.title}」`, impact: '只能删除草稿，不能恢复', templates: ['不发了'], danger: true, okText: '删除' })
  if (reason === null) return
  try {
    await api(`/api/admin/announcements/${a.id}`, { method: 'DELETE', body: { reason } })
    toast('已删除', 'success')
    await load()
  } catch (e) {
    toast(e.message, 'error')
  }
}
const pct = (r) => (r == null ? '未知' : `${Math.round(r * 1000) / 10}%`)
</script>

<template>
  <div>
    <section class="card mt-3">
      <div class="flex flex-wrap items-center gap-2 border-b border-line px-3.5 py-3">
        <div class="seg"><button v-for="t in TABS" :key="t[0]" :class="{ on: status === t[0] }" @click="status = t[0]">{{ t[1] }}</button></div>
        <button v-if="canWrite" class="btn btn-primary ml-auto" @click="newOne">新建公告</button>
      </div>
      <ATable :columns="columns" :rows="data?.items || []" :loading="!data" empty-text="还没有公告">
        <template #cell-title="{ row: a }"><button class="block w-full cursor-pointer border-0 bg-transparent p-0 text-left" @click="openRow(a)"><b class="font-medium break-words">{{ a.title }}</b><span class="block text-xs text-mute">{{ a.sent_at ? `${formatTime(a.sent_at)} 发送` : `${formatTime(a.created_at)} 创建` }}</span></button></template>
        <template #cell-audience="{ row: a }"><span class="text-[13px] text-ink-2">{{ a.audience_label }}</span></template>
        <template #cell-status="{ row: a }"><span class="tag" :class="a.status === 'sent' ? 'tag-ok' : 'tag-gray'">{{ a.status_label }}</span></template>
        <template #cell-read="{ row: a }"><span v-if="a.status === 'sent'" class="text-[13px] tabular-nums">{{ a.read ?? '未知' }} / {{ a.recipients ?? '未知' }}<b class="ml-1">{{ pct(a.read_rate) }}</b></span><span v-else class="text-mute">—</span></template>
        <template #cell-actions="{ row: a }"><span class="flex justify-end gap-1.5"><button class="btn btn-sm" @click="openRow(a)">{{ a.status === 'draft' && canWrite ? '编辑' : '查看' }}</button><button v-if="canWrite && a.status === 'draft'" class="btn btn-sm btn-danger" @click="remove(a)">删除</button></span></template>
      </ATable>
      <div v-if="data" class="flex items-center border-t border-line px-[18px] py-3 text-xs text-mute">
        共 {{ data.total }} 条 · 已读 = 点开过，或点了「全部已读」
        <button v-if="data.items.length < data.total" class="btn btn-sm ml-auto" @click="load(true)">加载更多</button>
      </div>
    </section>

    <ADrawer :open="open" :label="readonly || !canWrite ? '公告' : '编辑公告'" :width="520" @close="open = false">
      <template #header><h2 class="m-0 text-base font-semibold">{{ readonly ? '已发送的公告' : form.id ? '编辑公告' : '新建公告' }}</h2></template>
      <div class="space-y-3.5">
        <label class="block text-xs text-mute">标题<input v-model="form.title" class="input mt-1" maxlength="40" :disabled="readonly || !canWrite" /></label>
        <label class="block text-xs text-mute">内容<textarea v-model="form.text" rows="4" maxlength="500" class="input mt-1 h-auto resize-y py-2" :disabled="readonly || !canWrite" /></label>
        <label class="block text-xs text-mute">点开后去哪里（站内路径，可不填）<input v-model="form.link" class="input mt-1 font-mono" maxlength="300" placeholder="/categories" :disabled="readonly || !canWrite" /></label>
        <div>
          <p class="m-0 mb-1.5 text-xs text-mute">发给谁</p>
          <div class="seg"><button :class="{ on: form.all }" :disabled="readonly || !canWrite" @click="form.all = true; preview = null">所有用户</button><button :class="{ on: !form.all }" :disabled="readonly || !canWrite" @click="form.all = false; preview = null">按标签 / 渠道</button></div>
          <template v-if="!form.all">
            <p class="m-0 mt-3 mb-1.5 text-xs text-mute">标签（选了多个是任意一个）</p>
            <div class="flex flex-wrap gap-1.5"><button v-for="t in tagState.items" :key="t.id" type="button" class="tag cursor-pointer border-0 !h-8 !px-3" :class="[TAG_COLOR[t.color], form.tag_ids.includes(t.id) ? '' : 'opacity-40']" :disabled="readonly || !canWrite" :aria-pressed="form.tag_ids.includes(t.id)" @click="toggle('tag_ids', t.id)">{{ t.name }}</button><span v-if="!tagState.items.length" class="text-[13px] text-mute">还没有标签</span></div>
            <p class="m-0 mt-3 mb-1.5 text-xs text-mute">注册渠道</p>
            <div class="flex flex-wrap gap-1.5"><button v-for="c in CHANNELS" :key="c[0]" type="button" class="tag tag-gray cursor-pointer border-0 !h-8 !px-3" :class="form.channels.includes(c[0]) ? '!bg-primary-soft !text-primary' : 'opacity-60'" :disabled="readonly || !canWrite" :aria-pressed="form.channels.includes(c[0])" @click="toggle('channels', c[0])">{{ c[1] }}</button></div>
            <p class="m-0 mt-2 text-xs text-mute">标签和渠道都选时，同时符合才会收到；只发给正常状态的普通用户</p>
          </template>
        </div>
        <div v-if="readonly" class="rounded-lg bg-subtle p-3.5 text-[13px]">
          <p class="m-0">发给 <b class="tabular-nums">{{ view.recipients ?? '未知' }}</b> 人，已读 <b class="tabular-nums">{{ view.read ?? '未知' }}</b> 人（{{ pct(view.read_rate) }}）</p>
          <p class="m-0 mt-1 text-xs text-mute">{{ view.sent_by?.label || '' }} 于 {{ formatTime(view.sent_at) }} 发送 · 点了「全部已读」也算已读</p>
        </div>
        <div v-else-if="preview" class="rounded-lg p-3.5 text-[13px]" :class="preview.over_limit || !preview.count ? 'bg-bad-soft text-bad' : 'bg-primary-soft'">
          <p class="m-0 font-semibold">将发给 {{ preview.count }} 位用户<template v-if="preview.over_limit">，超过上限 {{ preview.max_recipients }}，请缩小范围</template><template v-else-if="!preview.count">，没有符合条件的用户</template></p>
          <p v-if="preview.sample.length" class="m-0 mt-1.5 flex flex-wrap gap-1.5"><span v-for="u in preview.sample" :key="u.id" class="tag tag-gray">{{ u.label }}</span><span v-if="preview.count > preview.sample.length" class="text-xs text-mute">等</span></p>
          <p class="m-0 mt-2 text-xs text-ink-2">用户铃铛里看到：<b>{{ preview.notification.title }}</b> {{ preview.notification.body }}</p>
        </div>
      </div>
      <template v-if="!readonly && canWrite" #footer>
        <div class="flex flex-wrap justify-end gap-2">
          <button class="btn" :disabled="!!busy || !valid" @click="save">保存草稿</button>
          <button class="btn" :disabled="!!busy || !valid" @click="doPreview">预览人数</button>
          <button class="btn btn-primary" :disabled="!!busy || !preview || !preview.count || preview.over_limit" @click="send">发送</button>
        </div>
      </template>
    </ADrawer>
  </div>
</template>
