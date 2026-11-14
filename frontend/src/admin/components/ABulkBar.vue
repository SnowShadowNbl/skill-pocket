<script setup>
import { computed, ref } from 'vue'
import Icon from '../../components/Icon.vue'
import { confirmDialog } from '../../composables/dialog'
import { toast } from '../../composables/toast'
import { mergeResults } from '../composables/bulk'
import { askReason } from '../composables/reason'
import AResultPanel from './AResultPanel.vue'

// 底部固定的批量操作栏：显示选中范围和数量，操作有影响时先走原因弹窗，执行后弹出逐项结果。
//   <ABulkBar :selection="sel" :actions="[{ key, label, icon?, danger?, more?, pick?, confirm?, reason?: { title, impact: (n) => string, templates, okText? }, run: (scope, reason, params) => Promise<{ results } | { task_id }> }]" @done="reload" />
//   more：放进「更多」菜单；pick：先让管理员选参数（async (n) => params | null，null 表示取消）；confirm：(n) => { title, message, okText, danger } 先确认
//   返回里同时有 results 和 task_id 的（异步操作）照常显示逐项结果，进度在右下角任务栏
//   选「全部筛选结果」后数量被别人改了（409 count_changed）会提示并清空选择，触发 @done 让页面重新拉取
const props = defineProps({
  selection: { type: Object, required: true },
  actions: { type: Array, required: true },
  noun: { type: String, default: '项' },
})
const emit = defineEmits(['done'])
const busy = ref(false)
const menu = ref(false)
const panel = ref({ open: false, title: '', results: [] })
let last = null

const show = computed(() => props.selection.count > 0)

async function exec(a) {
  menu.value = false
  let params
  if (a.pick) {
    params = await a.pick(props.selection.count)
    if (params == null) return
  }
  if (a.confirm) {
    const c = a.confirm(props.selection.count)
    if (!(await confirmDialog({ danger: a.danger, okText: a.label, ...c }))) return
  }
  let reason = ''
  if (a.reason) {
    reason = await askReason({
      title: a.reason.title,
      impact: a.reason.impact(props.selection.count),
      templates: a.reason.templates || [],
      danger: !!a.danger,
      okText: a.reason.okText || a.label,
    })
    if (reason === null) return
  }
  last = { a, reason, params, title: a.reason?.title || a.label }
  await run(props.selection.scope, false)
}

async function run(scope, isRetry) {
  const { a, reason, params, title } = last
  busy.value = true
  try {
    const data = await a.run(scope, reason, params)
    if (data?.task_id && !data.results) {
      toast('数量较多，已转为后台任务，进度在右下角任务栏', 'info')
      props.selection.clear()
      emit('done')
      return
    }
    panel.value = { open: true, title, results: isRetry ? mergeResults(panel.value.results, data.results) : data.results }
    if (!isRetry) props.selection.clear()
    emit('done', data)
  } catch (e) {
    if (e.code === 'count_changed') {
      toast('数量已变化，请重新选择', 'error')
      props.selection.clear()
      emit('done')
    } else toast(e.message, 'error')
  } finally {
    busy.value = false
  }
}
const retry = (ids) => run({ ids }, true)
</script>

<template>
  <div v-if="show" class="h-20" />
  <Transition name="fade">
    <div v-if="show" class="pointer-events-none fixed inset-x-0 bottom-0 z-30 px-3 pb-[max(12px,env(safe-area-inset-bottom))] lg:left-[224px] lg:px-6" role="region" aria-label="批量操作">
      <div class="card pointer-events-auto mx-auto flex max-w-[1360px] flex-wrap items-center gap-x-3 gap-y-2 px-4 py-2.5 shadow-[0_12px_32px_-12px_rgba(14,26,43,.3)]">
        <span class="text-[13px]">
          <template v-if="selection.mode === 'all'">已选全部筛选结果 <b class="tabular-nums">{{ selection.count }}</b> {{ noun }}</template>
          <template v-else>已选 <b class="tabular-nums">{{ selection.count }}</b> {{ noun }}</template>
        </span>
        <button v-if="selection.mode === 'ids' && selection.canSelectAll && selection.pageState === 'all'" class="text-[13px] text-primary hover:underline" @click="selection.selectAll()">选择全部筛选结果（共 {{ selection.total }} 条）</button>
        <button v-else-if="selection.mode === 'all'" class="text-[13px] text-primary hover:underline" @click="selection.selectPageOnly()">只选本页</button>
        <span class="ml-auto flex flex-wrap items-center gap-2">
          <button v-for="a in actions.filter((x) => !x.more)" :key="a.key" class="btn" :class="a.danger ? 'btn-danger' : 'btn-primary'" :disabled="busy" @click="exec(a)"><Icon v-if="a.icon" :name="a.icon" :size="14" />{{ a.label }}</button>
          <span v-if="actions.some((x) => x.more)" class="relative">
            <button class="btn" :aria-expanded="menu" aria-haspopup="menu" :disabled="busy" @click="menu = !menu">更多<Icon name="chevron-up" :size="14" /></button>
            <span v-if="menu" class="fixed inset-0 z-10" @click="menu = false" />
            <span v-if="menu" class="absolute right-0 bottom-full z-20 mb-1 flex min-w-40 flex-col rounded-lg border border-line bg-white p-1 shadow-[0_8px_24px_-8px_rgba(15,29,51,.2)]" role="menu">
              <button v-for="a in actions.filter((x) => x.more)" :key="a.key" class="flex min-h-10 items-center gap-2 rounded-md px-2.5 text-left text-[13px] hover:bg-subtle" :class="a.danger ? 'text-bad' : ''" role="menuitem" @click="exec(a)"><Icon v-if="a.icon" :name="a.icon" :size="14" />{{ a.label }}</button>
            </span>
          </span>
          <button class="btn" @click="selection.clear()">取消选择</button>
        </span>
      </div>
    </div>
  </Transition>
  <AResultPanel :open="panel.open" :title="panel.title" :results="panel.results" :retrying="busy" @retry="retry" @close="panel.open = false" />
</template>
