<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, formatTime, isCancelled } from '../../api'
import { confirmDialog, promptDialog } from '../../composables/dialog'
import { toast } from '../../composables/toast'
import ASelect from '../components/ASelect.vue'
import ATable from '../components/ATable.vue'
import { onActionError } from '../composables/handled'
import { askReason } from '../composables/reason'
import { useQueryFilters } from '../composables/useQueryFilters'

// 搜索词：首页「大家在搜」实际展示的词（可一键屏蔽）、屏蔽词表、搜不到结果的搜索（可标记已补收录）
const route = useRoute()
const router = useRouter()
const TABS = [['hot', '大家在搜'], ['empty', '无结果搜索'], ['block', '屏蔽词']]
const tab = computed(() => (TABS.some((t) => t[0] === route.query.tab) ? route.query.tab : 'hot'))
const setTab = (t) => router.replace({ query: { tab: t === 'hot' ? undefined : t } })
const busy = ref('')

const BLOCK_REASONS = ['无意义的词', '广告或引流', '敏感内容', '内部测试词']
async function block(term) {
  const reason = await askReason({ title: `屏蔽「${term}」？`, impact: '首页「大家在搜」不再展示这个词，立即生效', templates: BLOCK_REASONS, danger: true, okText: '屏蔽' })
  if (reason === null) return false
  try {
    await api('/api/admin/search-blocklist', { method: 'POST', body: { term, reason } })
    toast(`已屏蔽「${term}」`, 'success')
    return true
  } catch (e) {
    await onActionError(e)
    return false
  }
}

// ------------------------------------------------------------ 大家在搜
const hot = ref(null)
async function loadHot() {
  try {
    hot.value = await api('/api/admin/search-terms/hot')
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  }
}
const shown = computed(() => (hot.value?.items || []).filter((x) => x.status === 'shown'))
const hotColumns = [
  { key: 'term', label: '搜索词', mobile: 'title' },
  { key: 'people', label: '搜索人数', align: 'right', mobile: 'meta', mlabel: true },
  { key: 'status', label: '状态', mobile: 'meta' },
  { key: 'actions', label: '', align: 'right', mobile: 'action' },
]
async function blockHot(x) {
  busy.value = x.key
  if (await block(x.term)) await loadHot()
  busy.value = ''
}
async function unblock(id, term) {
  if (!(await confirmDialog({ title: `解除对「${term}」的屏蔽？`, okText: '解除' }))) return
  try {
    await api(`/api/admin/search-blocklist/${id}`, { method: 'DELETE' })
    toast('已解除屏蔽', 'success')
    loadHot()
    loadBlock()
  } catch (e) {
    await onActionError(e)
  }
}

// ------------------------------------------------------------ 无结果搜索
const { filters: ef, params: eParams, activeCount: eActive, reset: eReset } = useQueryFilters({ status: '', sort: '', days: '' })
const empty = ref(null)
const ePage = ref(1)
const eStatus = [{ value: '', label: '未处理' }, { value: 'covered', label: '已补收录' }, { value: 'all', label: '全部' }]
const eDays = [{ value: '', label: '近 30 天' }, { value: '7', label: '近 7 天' }, { value: '90', label: '近 90 天' }]
async function loadEmpty(more = false) {
  ePage.value = more ? ePage.value + 1 : 1
  const p = new URLSearchParams(eParams.value)
  p.set('status', ef.status === '' ? 'open' : ef.status)
  p.set('sort', ef.sort === 'recent' ? 'recent' : 'count')
  if (!ef.days) p.delete('days')
  p.set('page', ePage.value)
  p.set('page_size', 30)
  try {
    const d = await api(`/api/admin/search-terms/empty?${p}`)
    empty.value = more ? { ...d, items: [...empty.value.items, ...d.items] } : d
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  }
}
const emptyColumns = [
  { key: 'term', label: '搜索词', mobile: 'title' },
  { key: 'empty_count', label: '无结果次数', align: 'right', mobile: 'meta', mlabel: true },
  { key: 'last_at', label: '最近', mobile: 'meta' },
  { key: 'state', label: '状态', mobile: 'meta' },
  { key: 'actions', label: '', align: 'right', mobile: 'action' },
]
async function cover(x) {
  const note = await promptDialog({ title: `「${x.term}」已补收录？`, placeholder: '补收录了哪个条目（可不填）', maxlength: 100, okText: '标记已补收录' })
  if (note === null) return
  busy.value = x.id
  try {
    await api(`/api/admin/search-terms/${x.id}/cover`, { method: 'POST', body: { note } })
    await loadEmpty()
  } catch (e) {
    await onActionError(e, loadEmpty)
  } finally {
    busy.value = ''
  }
}
async function uncover(x) {
  busy.value = x.id
  try {
    await api(`/api/admin/search-terms/${x.id}/cover`, { method: 'DELETE' })
    await loadEmpty()
  } catch (e) {
    await onActionError(e, loadEmpty)
  } finally {
    busy.value = ''
  }
}
async function blockEmpty(x) {
  busy.value = x.id
  if (await block(x.term)) await loadEmpty()
  busy.value = ''
}

// ------------------------------------------------------------ 屏蔽词
const blocks = ref(null)
async function loadBlock() {
  try {
    blocks.value = await api('/api/admin/search-blocklist')
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  }
}
const addTerm = ref('')
async function addBlock() {
  const term = addTerm.value.trim()
  if (!term) return
  if (await block(term)) {
    addTerm.value = ''
    loadBlock()
  }
}

watch(tab, (t) => {
  if (t === 'hot') loadHot()
  else if (t === 'empty') loadEmpty()
  else loadBlock()
}, { immediate: true })
watch(() => eParams.value.toString(), () => tab.value === 'empty' && loadEmpty())
</script>

<template>
  <div>
    <div class="flex flex-wrap items-center gap-3">
      <h1 class="m-0 text-xl font-semibold">搜索词</h1>
      <div class="seg ml-auto"><button v-for="t in TABS" :key="t[0]" :class="{ on: tab === t[0] }" @click="setTab(t[0])">{{ t[1] }}</button></div>
    </div>

    <!-- 大家在搜 -->
    <template v-if="tab === 'hot'">
      <section class="card mt-5">
        <div class="card-hd"><h2>首页正在展示</h2><span v-if="hot" class="text-xs text-mute">近 {{ hot.window_days }} 天，至少 {{ hot.min_people }} 人搜过，最多 {{ hot.shown_max }} 个</span></div>
        <div class="card-bd">
          <div v-if="!hot" class="skeleton h-10" />
          <p v-else-if="!shown.length" class="m-0 text-[13px] text-mute">现在没有词可以展示</p>
          <p v-else class="m-0 flex flex-wrap gap-2">
            <span v-for="x in shown" :key="x.key" class="inline-flex items-center gap-1 rounded-full bg-primary-soft py-1 pr-1 pl-3 text-[13px] text-primary">
              {{ x.term }}<button class="grid h-6 w-6 place-items-center rounded-full text-primary/70 hover:bg-white hover:text-bad" :aria-label="`屏蔽 ${x.term}`" :disabled="busy === x.key" @click="blockHot(x)">×</button>
            </span>
          </p>
        </div>
      </section>
      <section class="card mt-3.5">
        <div class="card-hd"><h2>搜索词排行</h2></div>
        <ATable :columns="hotColumns" :rows="hot?.items || []" row-key="key" :loading="!hot" empty-text="近期没有搜索词">
          <template #cell-term="{ row: x }"><b class="font-medium break-all">{{ x.term }}</b></template>
          <template #cell-people="{ row: x }"><span class="tabular-nums">{{ x.people }}</span></template>
          <template #cell-status="{ row: x }">
            <span class="tag" :class="x.status === 'shown' ? 'tag-ok' : x.reason === 'blocked' ? 'tag-bad' : 'tag-gray'">{{ x.status === 'shown' ? '展示中' : '未展示' }}</span>
            <span v-if="x.reason_label" class="ml-1.5 text-xs text-mute">{{ x.reason_label }}<template v-if="x.block_reason">：{{ x.block_reason }}</template></span>
          </template>
          <template #cell-actions="{ row: x }">
            <button v-if="x.reason === 'blocked' && x.term_id" class="btn btn-sm" @click="unblock(x.term_id, x.term)">解除屏蔽</button>
            <button v-else-if="x.reason !== 'blocked'" class="btn btn-sm btn-danger" :disabled="busy === x.key" @click="blockHot(x)">屏蔽</button>
          </template>
        </ATable>
      </section>
    </template>

    <!-- 无结果搜索 -->
    <section v-else-if="tab === 'empty'" class="card mt-5">
      <div class="flex flex-wrap items-center gap-2.5 border-b border-line p-3.5">
        <div class="w-[130px]"><ASelect v-model="ef.status" :options="eStatus" label="状态" /></div>
        <div class="w-[130px]"><ASelect v-model="ef.days" :options="eDays" label="时间范围" /></div>
        <div class="seg"><button :class="{ on: ef.sort !== 'recent' }" @click="ef.sort = ''">按次数</button><button :class="{ on: ef.sort === 'recent' }" @click="ef.sort = 'recent'">按最近</button></div>
        <button v-if="eActive" class="btn h-9 text-mute" @click="eReset">重置</button>
      </div>
      <ATable :columns="emptyColumns" :rows="empty?.items || []" :loading="!empty" empty-text="没有符合条件的无结果搜索">
        <template #cell-term="{ row: x }"><b class="font-medium break-all">{{ x.term }}</b></template>
        <template #cell-empty_count="{ row: x }"><span class="tabular-nums">{{ x.empty_count }}</span><span class="ml-1 text-xs text-mute">/ 共搜 {{ x.searches }}</span></template>
        <template #cell-last_at="{ row: x }"><span class="text-xs whitespace-nowrap text-mute">{{ x.last_at ? formatTime(x.last_at) : '未知' }}</span></template>
        <template #cell-state="{ row: x }">
          <span v-if="x.covered" class="tag tag-ok">已补收录</span><span v-else-if="x.blocked" class="tag tag-bad">已屏蔽</span><span v-else class="tag tag-warn">未处理</span>
          <span v-if="x.covered?.note" class="ml-1.5 text-xs text-mute">{{ x.covered.note }}</span>
        </template>
        <template #cell-actions="{ row: x }">
          <span class="flex justify-end gap-2">
            <button v-if="x.covered" class="btn btn-sm" :disabled="busy === x.id" @click="uncover(x)">取消标记</button>
            <button v-else class="btn btn-sm btn-primary" :disabled="busy === x.id" @click="cover(x)">已补收录</button>
            <button v-if="!x.blocked" class="btn btn-sm btn-danger" :disabled="busy === x.id" @click="blockEmpty(x)">屏蔽</button>
          </span>
        </template>
      </ATable>
      <div v-if="empty" class="flex items-center border-t border-line px-[18px] py-3 text-xs text-mute">
        共 {{ empty.total }} 个词
        <button v-if="empty.items.length < empty.total" class="btn btn-sm ml-auto" @click="loadEmpty(true)">加载更多</button>
      </div>
    </section>

    <!-- 屏蔽词 -->
    <template v-else>
      <form class="card mt-5 flex flex-wrap gap-2.5 p-3.5" @submit.prevent="addBlock">
        <input v-model="addTerm" class="input min-w-0 flex-1 sm:max-w-sm" placeholder="要屏蔽的词" maxlength="30" aria-label="要屏蔽的词" />
        <button class="btn btn-primary" :disabled="!addTerm.trim()">屏蔽</button>
      </form>
      <section class="card mt-3.5">
        <div class="card-hd"><h2>屏蔽词表</h2><span v-if="blocks" class="text-xs text-mute">{{ blocks.items.length }} 个</span></div>
        <div v-if="!blocks" class="p-3.5"><div class="skeleton h-24" /></div>
        <p v-else-if="!blocks.items.length" class="empty">还没有屏蔽词</p>
        <ul v-else class="m-0 list-none p-0">
          <li v-for="b in blocks.items" :key="b.id" class="flex items-center gap-3 border-b border-line px-4 py-2.5 last:border-0">
            <span class="min-w-0 flex-1"><b class="font-medium break-all">{{ b.term }}</b>
              <span class="block text-xs text-mute">{{ b.blocked?.by?.label }} · {{ b.blocked?.at ? formatTime(b.blocked.at) : '' }}<template v-if="b.blocked?.reason"> · {{ b.blocked.reason }}</template></span></span>
            <button class="btn btn-sm" @click="unblock(b.id, b.term)">解除</button>
          </li>
        </ul>
      </section>
    </template>
  </div>
</template>
