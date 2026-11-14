<script setup>
import { computed, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { api, formatTime, isCancelled } from '../../api'
import { toast } from '../../composables/toast'
import AFilterBar from './AFilterBar.vue'
import ATable from './ATable.vue'
import { useQueryFilters } from '../composables/useQueryFilters'

// 额度账本：发放、充值、手动调整、重置。「实际充值金额」是收到的钱，和估算成本分开看
const { filters, params, activeCount, reset } = useQueryFilters({ kind: '', user_id: '', created: { from: '', to: '' } })
const data = ref(null)
const page = ref(1)
const kindOptions = computed(() => [{ value: '', label: '全部类型' }, ...Object.entries(data.value?.kinds || {}).map(([k, v]) => ({ value: k, label: v }))])
const fields = computed(() => [
  { key: 'kind', type: 'select', label: '类型', options: kindOptions.value },
  { key: 'created', type: 'daterange', label: '发生日期' },
])
const columns = [
  { key: 'user', label: '账号', mobile: 'title' },
  { key: 'kind', label: '类型', mobile: 'meta' },
  { key: 'delta', label: '额度变化', align: 'right', mobile: 'meta' },
  { key: 'balance_after', label: '变化后余额', align: 'right', hideBelow: 'md', mobile: 'hide' },
  { key: 'amount', label: '收款', align: 'right', hideBelow: 'md', mobile: 'hide' },
  { key: 'note', label: '备注', hideBelow: 'lg', mobile: 'sub' },
  { key: 'operator', label: '操作人 / 时间', align: 'right', mobile: 'hide' },
]
const num = (n) => (n == null ? '—' : Number(n).toLocaleString())

async function load(more = false) {
  page.value = more ? page.value + 1 : 1
  const p = new URLSearchParams(params.value)
  p.set('page', page.value)
  p.set('page_size', 30)
  try {
    const d = await api(`/api/admin/ai/ledger?${p}`)
    data.value = more ? { ...d, items: [...data.value.items, ...d.items] } : d
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  }
}
watch(() => params.value.toString(), () => load(), { immediate: true })
</script>

<template>
  <section class="card">
    <div class="card-hd"><h2>额度账本</h2><span v-if="data" class="text-xs text-mute">历史收到的充值合计 <b class="text-ink tabular-nums">¥{{ data.recharged_yuan_total ?? 0 }}</b></span></div>
    <AFilterBar :filters="filters" :fields="fields" :active-count="activeCount" @reset="reset" />
    <p v-if="filters.user_id" class="m-0 flex items-center gap-2 border-b border-line bg-primary-soft px-[18px] py-2 text-[13px] text-primary">只看用户 #{{ filters.user_id }}<button class="ml-auto underline" @click="filters.user_id = ''">看全部</button></p>
    <ATable :columns="columns" :rows="data?.items || []" :loading="!data" empty-text="没有符合条件的记录">
      <template #cell-user="{ row: r }"><RouterLink :to="{ path: '/users', query: { id: r.user.id } }" class="font-medium text-ink no-underline hover:text-primary">{{ r.user.label }}</RouterLink></template>
      <template #cell-kind="{ row: r }"><span class="tag" :class="r.kind === 'recharge' ? 'tag-ok' : 'tag-gray'">{{ r.kind_label }}</span></template>
      <template #cell-delta="{ row: r }"><b class="tabular-nums" :class="r.delta >= 0 ? 'text-ok' : 'text-bad'">{{ r.delta >= 0 ? '+' : '' }}{{ num(r.delta) }}</b></template>
      <template #cell-balance_after="{ row: r }"><span class="tabular-nums">{{ num(r.balance_after) }}</span></template>
      <template #cell-amount="{ row: r }"><span class="tabular-nums">{{ r.amount_yuan ? `¥${r.amount_yuan}` : '—' }}</span></template>
      <template #cell-note="{ row: r }"><span class="text-ink-2">{{ r.note || '—' }}</span></template>
      <template #cell-operator="{ row: r }"><span class="text-xs whitespace-nowrap text-mute">{{ r.operator?.label || '系统' }} · {{ formatTime(r.created_at) }}</span></template>
    </ATable>
    <div v-if="data" class="flex items-center border-t border-line px-[18px] py-3 text-xs text-mute">
      共 {{ data.total }} 条
      <button v-if="data.items.length < data.total" class="btn btn-sm ml-auto" @click="load(true)">加载更多</button>
    </div>
  </section>
</template>
