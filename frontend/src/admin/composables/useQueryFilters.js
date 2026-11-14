import { computed, reactive, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

// 筛选条件与地址栏 query 双向同步：刷新、返回列表、分享链接都保留条件。
//   const { filters, params, activeCount, reset, apply, query } = useQueryFilters({ q: '', status: '', created: { from: '', to: '' }, low: false })
//   - 默认值决定类型：字符串 / 布尔（地址里写 1）/ 日期区间 { from, to }（地址里是 <键>_from、<键>_to）
//   - filters 绑到控件上随时改；params（URLSearchParams，只含与默认值不同的条件）在搜索框停手 250ms 后更新，列表 watch 它来取数
//   - 地址里不属于筛选的参数（tab、id 等）原样保留
const isRange = (v) => v && typeof v === 'object'
const clone = (f) => JSON.parse(JSON.stringify(f))
const sig = (q) => JSON.stringify(Object.entries(q).sort())

export function useQueryFilters(schema, { debounce = 250 } = {}) {
  const route = useRoute()
  const router = useRouter()
  const keys = Object.keys(schema)
  const own = new Set(keys.flatMap((k) => [k, `${k}_from`, `${k}_to`]))

  const read = (query) => {
    const out = {}
    for (const k of keys) {
      const d = schema[k]
      if (isRange(d)) out[k] = { from: String(query[`${k}_from`] || ''), to: String(query[`${k}_to`] || '') }
      else if (typeof d === 'boolean') out[k] = query[k] === '1'
      else out[k] = query[k] == null ? d : String(query[k])
    }
    return out
  }
  const active = (k, f) => (isRange(schema[k]) ? !!(f[k].from || f[k].to) : typeof schema[k] === 'boolean' ? f[k] : String(f[k]).trim() !== schema[k])
  // 序列化成地址里的 query：只写与默认值不同的条件
  const toQuery = (f) => {
    const q = {}
    for (const k of keys) {
      if (!active(k, f)) continue
      if (isRange(schema[k])) {
        if (f[k].from) q[`${k}_from`] = f[k].from
        if (f[k].to) q[`${k}_to`] = f[k].to
      } else q[k] = typeof schema[k] === 'boolean' ? '1' : String(f[k]).trim()
    }
    return q
  }

  const filters = reactive(read(route.query))
  const applied = reactive(clone(filters)) // 防抖之后真正生效的条件

  const params = computed(() => new URLSearchParams(toQuery(applied)))
  const activeCount = computed(() => keys.filter((k) => active(k, filters)).length)

  let timer
  function commit() {
    clearTimeout(timer)
    Object.assign(applied, clone(filters))
    const mine = toQuery(filters)
    if (sig(mine) === sig(toQuery(read(route.query)))) return
    const rest = Object.fromEntries(Object.entries(route.query).filter(([k]) => !own.has(k)))
    router.replace({ query: { ...rest, ...mine } })
  }

  // 在文字框里打字时等停手再生效；选择类立即生效
  watch(filters, () => {
    clearTimeout(timer)
    const typing = document.activeElement?.tagName === 'INPUT' && sig(toQuery(filters)) !== sig(toQuery(applied))
    if (typing) timer = setTimeout(commit, debounce)
    else commit()
  }, { deep: true })

  // 前进 / 后退或别处改了地址：反向同步
  watch(() => route.query, (q) => {
    const next = read(q)
    if (sig(toQuery(next)) === sig(toQuery(filters))) return
    clearTimeout(timer)
    Object.assign(filters, next)
    Object.assign(applied, clone(next))
  })

  function reset() {
    Object.assign(filters, read({}))
  }
  // 用一份 query 字典整体替换当前条件（应用保存的视图）
  function apply(q) {
    Object.assign(filters, read(q || {}))
  }
  const query = computed(() => toQuery(filters)) // 当前条件的 query 字典（保存视图用）
  return { filters, params, activeCount, reset, apply, query }
}
