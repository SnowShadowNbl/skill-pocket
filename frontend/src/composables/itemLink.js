import { useRoute } from 'vue-router'

// 打开条目详情：在当前页面上叠一个侧滑抽屉，底下的页面（主页 / 榜单 / 我的 / 收藏 / 对比结果）保持不动。
// 当前页面支持详情抽屉（有 items/:id 子路由）就用「当前路径/items/:id」，并带上当前的筛选参数；否则退回主页上的抽屉。
export function itemLinkFor(route, id) {
  const top = route.matched[0]
  const supports = top?.children?.some((c) => c.path === 'items/:id')
  const base = supports ? route.path.replace(/\/items\/\d+\/?$/, '').replace(/\/$/, '') : ''
  return { path: `${base}/items/${id}`, query: supports ? route.query : {} }
}

export function useItemLink() {
  const route = useRoute()
  return (id) => itemLinkFor(route, id)
}
