import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

// 列表 → 详情：详情的 id 写进地址（?id=），刷新、分享链接都能直接打开；关闭后回到原来的列表位置和筛选条件。
//   const detail = useDetailRoute('id', { legacy: ['user'] })
//   detail.id（字符串或 null）/ detail.open(id) / detail.close()
//   - 从列表点开用 push，手机上按返回键就是关闭；直接打开带 id 的链接时，关闭改为去掉 id（不离开本页）
//   - legacy：旧链接的参数名（如 ?user=），进页面时自动改写为 ?id=
const sig = (q) => JSON.stringify(Object.entries(q).sort())

export function useDetailRoute(key = 'id', { legacy = [] } = {}) {
  const route = useRoute()
  const router = useRouter()
  let pushed = false
  let openedAt = '' // 打开时（去掉 id 后）的 query，用来判断关闭时能不能直接后退

  const id = computed(() => (route.query[key] ? String(route.query[key]) : null))

  for (const old of legacy) {
    if (route.query[old] && !route.query[key]) {
      const { [old]: v, ...rest } = route.query
      router.replace({ query: { ...rest, [key]: String(v) } })
    }
  }

  function open(v) {
    const query = { ...route.query, [key]: String(v) }
    if (id.value) router.replace({ query }) // 已经开着时换一个，不叠历史记录
    else {
      pushed = true
      openedAt = sig(route.query)
      router.push({ query })
    }
  }
  function close() {
    if (!id.value) return
    const { [key]: _, ...rest } = route.query
    // 抽屉开着时筛选条件变过（replace），后退会退回改之前的条件，这时改成原地去掉 id
    if (pushed && sig(rest) === openedAt) {
      pushed = false
      router.back()
    } else {
      pushed = false
      router.replace({ query: rest })
    }
  }
  return { id, open, close }
}
