import { computed } from 'vue'
import { authState } from '../../composables/auth'

// 后台权限：按角色和模块判断能不能看、能不能改。
//   接口（/api/auth/me）返回 permissions{ 模块key: 'r' | 'w' } 时以它为准；还没返回时按角色兜底（超级管理员全部可写，其他管理员和现在一致）。
//   前端只负责隐藏入口、禁用按钮，真正的拦截在后端接口（无权限返回 403 no_permission）。
export const ROLE_LABEL = { admin: '超级管理员', super: '超级管理员', moderator: '内容审核', support: '客服', viewer: '只读', subadmin: '子管理员' }
const SUPER_ONLY = new Set(['staff', 'reason-templates'])

const level = (key) => {
  const u = authState.user
  if (!u) return ''
  if (u.permissions) return u.permissions[key] || ''
  if (['admin', 'super'].includes(u.role)) return 'w'
  return SUPER_ONLY.has(key) ? 'r' : 'w'
}
// can('users') 能看；can('users', 'w') 能改
export const can = (key, need = 'r') => {
  const l = level(key)
  return need === 'w' ? l === 'w' : l === 'r' || l === 'w'
}
// 单项能力：导出带邮箱、单发站内消息、以用户视角查看……（接口返回 capabilities[]；没返回时只有超级管理员有）
export const hasCap = (name) => {
  const u = authState.user
  return !!u && (Array.isArray(u.capabilities) ? u.capabilities.includes(name) : ['admin', 'super'].includes(u.role))
}
export function usePermissions() {
  return { can, hasCap, role: computed(() => authState.user?.role), roleLabel: computed(() => ROLE_LABEL[authState.user?.role] || '管理员') }
}
