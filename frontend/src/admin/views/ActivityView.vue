<script setup>
import { computed, ref, watch } from 'vue'
import { api, formatTime, isCancelled } from '../../api'
import Icon from '../../components/Icon.vue'
import { toast } from '../../composables/toast'
import AFilterBar from '../components/AFilterBar.vue'
import ALogItem from '../components/ALogItem.vue'
import ATable from '../components/ATable.vue'
import { useQueryFilters } from '../composables/useQueryFilters'

// 操作日志：用户、访客、管理员和系统的关键操作；管理员操作带原因、修改前后和结果
const data = ref(null)
const page = ref(1)
const { filters, params, activeCount, reset } = useQueryFilters({ q: '', actor: '', action: '', result: '', created: { from: '', to: '' }, user_id: '', target_user_id: '' })

const ACTOR = { user: ['用户', 'tag-gray'], admin: ['管理员', 'tag-blue'], guest: ['访客', 'tag-gray'], system: ['系统', 'tag-warn'] }
const actorOptions = [{ value: '', label: '全部角色' }, { value: 'user', label: '用户' }, { value: 'admin', label: '管理员' }, { value: 'guest', label: '访客' }, { value: 'system', label: '系统' }]
const resultOptions = [{ value: '', label: '全部结果' }, { value: 'ok', label: '成功' }, { value: 'failed', label: '失败' }]
const actionOptions = computed(() => [{ value: '', label: '全部操作' }, ...Object.entries(data.value?.actions || {}).map(([k, v]) => ({ value: k, label: v }))])
const fields = computed(() => [
  { key: 'q', type: 'search', label: '搜索操作内容' },
  { key: 'actor', type: 'select', label: '角色', options: actorOptions },
  { key: 'action', type: 'select', label: '操作类型', options: actionOptions.value },
  { key: 'result', type: 'select', label: '结果', options: resultOptions },
  { key: 'created', type: 'daterange', label: '操作时间' },
])
const columns = [
  { key: 'created_at', label: '时间', mobile: 'sub', class: 'w-36' },
  { key: 'who', label: '角色 / 操作', mobile: 'title', class: 'w-44' },
  { key: 'content', label: '内容', mobile: 'meta', mclass: 'w-full' },
  { key: 'ip', label: 'IP / 归属地', hideBelow: 'lg', mobile: 'hide', class: 'w-56' },
]

async function load(more = false) {
  page.value = more ? page.value + 1 : 1
  const p = new URLSearchParams(params.value)
  p.set('page', page.value)
  p.set('page_size', 50)
  try {
    const d = await api(`/api/admin/activity?${p}`)
    data.value = more ? { ...d, items: [...data.value.items, ...d.items] } : d
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  }
}
watch(() => params.value.toString(), () => load(), { immediate: true })
</script>

<template>
  <div>
    <h1 class="m-0 mb-5 text-xl font-semibold">操作日志</h1>

    <section class="card">
      <AFilterBar :filters="filters" :fields="fields" :active-count="activeCount" @reset="reset" />
      <p v-if="filters.user_id || filters.target_user_id" class="m-0 flex items-center gap-2 border-b border-line bg-primary-soft px-[18px] py-2 text-[13px] text-primary">
        <Icon name="user" :size="14" />{{ filters.user_id ? `只看用户 #${filters.user_id} 的操作` : `只看对用户 #${filters.target_user_id} 的操作` }}
        <button class="ml-auto underline" @click="filters.user_id = ''; filters.target_user_id = ''">看全部</button>
      </p>
      <ATable :columns="columns" :rows="data?.items || []" :loading="!data" empty-text="没有符合条件的记录">
        <template #cell-created_at="{ row: r }"><span class="text-xs whitespace-nowrap text-mute tabular-nums">{{ formatTime(r.created_at) }}</span></template>
        <template #cell-who="{ row: r }">
          <span class="flex flex-wrap gap-1">
            <span class="tag" :class="ACTOR[r.actor]?.[1]">{{ ACTOR[r.actor]?.[0] || r.actor }}</span>
            <span class="tag tag-blue">{{ r.action_label }}</span>
            <span v-if="r.result === 'failed'" class="tag tag-bad">失败</span>
          </span>
        </template>
        <template #cell-content="{ row: r }">
          <ALogItem :row="r" @filter-user="(id) => (filters.user_id = String(id))" @filter-target="(id) => (filters.target_user_id = String(id))" />
          <span v-if="r.ip" class="mt-0.5 block text-xs text-mute lg:hidden">{{ r.geo || '未知地区' }} · {{ r.ip }}</span>
        </template>
        <template #cell-ip="{ row: r }">
          <span class="text-xs"><template v-if="r.ip">{{ r.geo || '未知地区' }}<span class="block font-mono text-mute">{{ r.ip }}</span></template><span v-else class="text-mute">—</span></span>
        </template>
      </ATable>
      <div v-if="data" class="flex items-center border-t border-line px-[18px] py-3 text-xs text-mute">
        共 {{ data.total }} 条
        <button v-if="data.items.length < data.total" class="btn btn-sm ml-auto" @click="load(true)">加载更多</button>
      </div>
    </section>
  </div>
</template>
