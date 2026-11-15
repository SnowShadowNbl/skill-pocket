import { reactive, watch } from 'vue'
import { authState } from './auth'
import { openBindWechat } from './quota'

// v3.3.100 只有邮箱、还没领过免费额度的账号：主动提示「绑定微信领取额度」
// - 登录（含注册）后自动弹一次绑定窗口，每个账号在本机只弹一次
// - 首页搜索框下方的提示条，关掉后本账号在本机不再显示
const SEEN = 'skp_bind_tip_seen'
const HIDE = 'skp_bind_tip_hidden'
const readSet = (k) => {
  try {
    return new Set(JSON.parse(localStorage.getItem(k) || '[]'))
  } catch {
    return new Set()
  }
}
const writeSet = (k, s) => {
  try {
    localStorage.setItem(k, JSON.stringify([...s].slice(-50)))
  } catch {}
}
export const bindTip = reactive({ hidden: readSet(HIDE) })

export const needsWechat = () => !!authState.user?.needs_wechat

export function hideBindBar() {
  const uid = authState.user?.id
  if (!uid) return
  const s = new Set(bindTip.hidden)
  s.add(uid)
  bindTip.hidden = s
  writeSet(HIDE, s)
}
export const showBindBar = () => needsWechat() && !bindTip.hidden.has(authState.user.id)

watch(
  () => authState.user && authState.user.id,
  (uid) => {
    if (!uid || !needsWechat()) return
    const seen = readSet(SEEN)
    if (seen.has(uid)) return
    seen.add(uid)
    writeSet(SEEN, seen)
    setTimeout(() => needsWechat() && openBindWechat('tip'), 600) // 等登录框收起再弹
  },
  { immediate: true },
)
