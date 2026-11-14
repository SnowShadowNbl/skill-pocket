import { computed, reactive, ref, watch } from 'vue'

// 列表勾选：「本页全选」和「全选当前筛选结果（共 N 条）」两种范围。
//   const sel = useSelection({ rows: computed(() => data.value?.items || []), total: computed(() => data.value?.total || 0), params: uParams })
//   sel.count / sel.mode（'ids' | 'all'）/ sel.pageState（'none' | 'some' | 'all'）/ sel.canSelectAll
//   sel.has(id) / sel.toggle(id) / sel.togglePage() / sel.selectAll() / sel.selectPageOnly() / sel.clear()
//   sel.scope：选具体条目时是 { ids }；选全部筛选结果时是 { filter, exclude, total }，由后端按筛选条件执行
//   筛选条件一变就自动清空
export function useSelection({ rows, total, params, key = 'id', selectable = () => true }) {
  const mode = ref('ids')
  const picked = reactive(new Set())
  const excluded = reactive(new Set())

  const pageRows = computed(() => rows.value.filter(selectable))
  const count = computed(() => (mode.value === 'all' ? Math.max(0, total.value - excluded.size) : picked.size))
  const has = (id) => (mode.value === 'all' ? !excluded.has(id) : picked.has(id))
  const pageState = computed(() => {
    const n = pageRows.value.filter((r) => has(r[key])).length
    return n === 0 ? 'none' : n === pageRows.value.length ? 'all' : 'some'
  })
  const canSelectAll = computed(() => total.value > rows.value.length)

  function toggle(id) {
    const set = mode.value === 'all' ? excluded : picked
    set.has(id) ? set.delete(id) : set.add(id)
  }
  function togglePage() {
    const on = pageState.value !== 'all'
    for (const r of pageRows.value) {
      const id = r[key]
      if (mode.value === 'all') on ? excluded.delete(id) : excluded.add(id)
      else on ? picked.add(id) : picked.delete(id)
    }
  }
  function selectAll() {
    mode.value = 'all'
    picked.clear()
    excluded.clear()
  }
  function selectPageOnly() {
    mode.value = 'ids'
    excluded.clear()
    picked.clear()
    for (const r of pageRows.value) picked.add(r[key])
  }
  function clear() {
    mode.value = 'ids'
    picked.clear()
    excluded.clear()
  }
  const scope = computed(() => (mode.value === 'all'
    ? { filter: Object.fromEntries(params?.value || []), exclude: [...excluded], total: total.value }
    : { ids: [...picked] }))

  if (params) watch(() => params.value.toString(), clear)
  return reactive({ mode, count, has, pageState, canSelectAll, toggle, togglePage, selectAll, selectPageOnly, clear, scope, total, selectable })
}
