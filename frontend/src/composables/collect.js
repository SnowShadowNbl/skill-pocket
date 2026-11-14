import { reactive } from 'vue'
import { requireLogin } from './auth'

// v3.0「新增 Skill」并入首页搜索框的 GitHub 标签：顶栏「收录」、手机底栏加号都走这里，
// 切到 GitHub 标签并聚焦搜索框（focus 自增，首页监听）
export const homeSignal = reactive({ focus: 0, pickFile: 0 })

export async function goCollect(router, { pickFile = false } = {}) {
  if (!(await requireLogin('登录后就可以收录 Skill'))) return
  await router.push({ path: '/', query: { scope: 'github' } })
  if (pickFile) homeSignal.pickFile++
  else homeSignal.focus++
}

// v3.2 手机底栏加号气泡的「本站搜索」：回到首页站内标签并聚焦搜索框（不需要登录）
export async function goSiteSearch(router) {
  await router.push({ path: '/' })
  homeSignal.focus++
}
