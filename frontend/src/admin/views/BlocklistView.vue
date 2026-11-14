<script setup>
import { ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { api, formatTime, isCancelled } from '../../api'
import { confirmDialog } from '../../composables/dialog'
import { toast } from '../../composables/toast'
import AFilterBar from '../components/AFilterBar.vue'
import ASelect from '../components/ASelect.vue'
import ATable from '../components/ATable.vue'
import { onActionError } from '../composables/handled'
import { askReason } from '../composables/reason'
import { useQueryFilters } from '../composables/useQueryFilters'

// 黑名单：被列入的仓库 / 作者，自动采集、用户提交、管理员导入都会拦住
const { filters, params, activeCount, reset } = useQueryFilters({ q: '', kind: '' })
const data = ref(null)
const page = ref(1)
const kindOptions = [{ value: '', label: '全部类型' }, { value: 'repo', label: '仓库' }, { value: 'owner', label: '作者' }]
const fields = [
  { key: 'q', type: 'search', label: '搜索黑名单', placeholder: '搜索仓库或作者' },
  { key: 'kind', type: 'select', label: '类型', options: kindOptions },
]
const columns = [
  { key: 'value', label: '对象', mobile: 'title' },
  { key: 'kind', label: '类型', mobile: 'meta' },
  { key: 'reason', label: '原因', mobile: 'sub' },
  { key: 'source', label: '来源', hideBelow: 'md', mobile: 'meta' },
  { key: 'by', label: '操作人 / 时间', hideBelow: 'lg', mobile: 'hide' },
  { key: 'actions', label: '', align: 'right', mobile: 'action' },
]

async function load(more = false) {
  page.value = more ? page.value + 1 : 1
  const p = new URLSearchParams(params.value)
  p.set('page', page.value)
  p.set('page_size', 50)
  try {
    const d = await api(`/api/admin/blocklist?${p}`)
    data.value = more ? { ...d, items: [...data.value.items, ...d.items] } : d
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  }
}
watch(() => params.value.toString(), () => load(), { immediate: true })

// ------------------------------------------------------------ 添加
const form = ref({ kind: 'repo', value: '' })
const formKinds = [{ value: 'repo', label: '仓库' }, { value: 'owner', label: '作者' }]
const REASONS_BLOCK = ['作者要求下架', '涉嫌侵权', '内容违规', '质量太差']
const busy = ref(false)
const hit = ref(null) // 刚加入的这条命中了多少已上线条目
async function add() {
  const value = form.value.value.trim()
  if (!value) return
  const reason = await askReason({
    title: `把${form.value.kind === 'repo' ? '仓库' : '作者'}「${value}」加入黑名单？`,
    impact: '自动采集、用户提交、管理员导入都会拦住；已收录的条目不会自动下线',
    templates: REASONS_BLOCK,
    danger: true,
    okText: '加入黑名单',
  })
  if (reason === null) return
  busy.value = true
  try {
    const r = await api('/api/admin/blocklist', { method: 'POST', body: { kind: form.value.kind, value, reason } })
    toast('已加入黑名单', 'success')
    hit.value = r.published_items ? { value: r.value || value, n: r.published_items } : null
    form.value.value = ''
    load()
  } catch (e) {
    await onActionError(e)
  } finally {
    busy.value = false
  }
}
async function remove(b) {
  if (!(await confirmDialog({ title: `把「${b.value}」移出黑名单？`, message: '之后可以被重新收录。', okText: '移出' }))) return
  try {
    await api(`/api/admin/blocklist/${b.id}`, { method: 'DELETE' })
    toast('已移出黑名单', 'success')
    load()
  } catch (e) {
    await onActionError(e, load)
  }
}
</script>

<template>
  <div>
    <h1 class="m-0 mb-5 text-xl font-semibold">黑名单</h1>
    <form class="card flex flex-wrap items-center gap-2.5 p-3.5" @submit.prevent="add">
      <div class="w-[110px]"><ASelect v-model="form.kind" :options="formKinds" label="类型" /></div>
      <input v-model="form.value" class="input min-w-0 flex-1 sm:max-w-md" :placeholder="form.kind === 'repo' ? 'owner/name 或 GitHub 链接' : '作者账号名'" maxlength="200" :aria-label="form.kind === 'repo' ? '仓库' : '作者'" />
      <button class="btn btn-primary" :disabled="busy || !form.value.trim()">加入黑名单</button>
    </form>
    <p v-if="hit" class="m-0 mt-3 flex flex-wrap items-center gap-2 rounded-lg bg-warn-soft px-3.5 py-2.5 text-[13px] text-warn">
      「{{ hit.value }}」有 {{ hit.n }} 个已上线条目，没有自动下线
      <RouterLink :to="{ path: '/content', query: { q: hit.value } }" class="font-medium underline">去内容管理处理</RouterLink>
      <button class="ml-auto underline" @click="hit = null">知道了</button>
    </p>

    <section class="card mt-3.5">
      <AFilterBar :filters="filters" :fields="fields" :active-count="activeCount" @reset="reset" />
      <ATable :columns="columns" :rows="data?.items || []" :loading="!data" empty-text="黑名单是空的">
        <template #cell-value="{ row: b }"><b class="font-medium break-all">{{ b.value }}</b></template>
        <template #cell-kind="{ row: b }"><span class="tag tag-gray">{{ b.kind_label }}</span></template>
        <template #cell-reason="{ row: b }"><span class="text-ink-2">{{ b.reason || '—' }}</span></template>
        <template #cell-source="{ row: b }"><span class="tag" :class="b.source === 'takedown' ? 'tag-blue' : 'tag-gray'">{{ b.source === 'takedown' ? '下架申请' : '手动添加' }}</span></template>
        <template #cell-by="{ row: b }"><span class="text-xs text-mute">{{ b.by?.label }} · {{ formatTime(b.at) }}</span></template>
        <template #cell-actions="{ row: b }"><button class="btn btn-sm" @click="remove(b)">移出</button></template>
      </ATable>
      <div v-if="data" class="flex items-center border-t border-line px-[18px] py-3 text-xs text-mute">
        共 {{ data.total }} 条
        <button v-if="data.items.length < data.total" class="btn btn-sm ml-auto" @click="load(true)">加载更多</button>
      </div>
    </section>
  </div>
</template>
