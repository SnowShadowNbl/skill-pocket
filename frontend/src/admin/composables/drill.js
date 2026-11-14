import { useRouter } from 'vue-router'
import { MODULES } from '../modules'

// 指标下钻：接口给 drill: { module, query }，跳到对应后台页面并带上筛选
export function useDrill() {
  const router = useRouter()
  return (d) => {
    const m = d && MODULES.find((x) => x.key === d.module)
    if (m) router.push({ path: m.path, query: d.query || {} })
  }
}
