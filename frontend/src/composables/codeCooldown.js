// v3.3.17 统一的「获取验证码」：所有入口（登录、找回密码、绑定邮箱、改密码、注销）共用一份倒计时。
// - 按「用途 + 邮箱」记冷却到期时间，关掉弹窗再打开、换个入口，倒计时都还在，不会出现「按钮能点、点了没反应」。
// - 已登录不做人机校验（后端 v3.3.11 起免 PoW），未登录才算 PoW。
// - 后端返回 429 时，从提示里读出等待秒数接着倒计时，并把后端给的原因原样抛出给页面提示。
import { reactive, ref } from 'vue'
import { api } from '../api'
import { authState } from './auth'
import { solveChallenge } from './pow'

const until = reactive({}) // key → 冷却结束的时间戳（毫秒）
const now = ref(Date.now())
let ticker = null

function tick() {
  now.value = Date.now()
  if (!Object.values(until).some((t) => t > now.value)) {
    clearInterval(ticker)
    ticker = null
  }
}
function arm(key, seconds) {
  until[key] = Date.now() + seconds * 1000
  now.value = Date.now()
  if (!ticker) ticker = setInterval(tick, 1000)
}

export const codeKey = (purpose, email = '') => `${purpose}:${(email || '').trim().toLowerCase()}`

/** 剩余冷却秒数（响应式，模板里直接用） */
export function codeLeft(purpose, email = '') {
  const t = until[codeKey(purpose, email)] || 0
  return Math.max(0, Math.ceil((t - now.value) / 1000))
}

export const codeLabel = (left) => `${left} 秒后可重新获取`

/**
 * 发送验证码。onPow 在开始人机校验时回调（页面可显示「安全校验中…」）。
 * 成功返回后端结果（含 cooldown、dev_code）；失败抛出带后端原因的错误。
 */
export async function requestCode({ purpose, email = '', onPow } = {}) {
  const key = codeKey(purpose, email)
  const left = codeLeft(purpose, email)
  if (left > 0) throw new Error(codeLabel(left))
  let pow = {}
  if (!authState.user) {
    onPow?.()
    pow = await solveChallenge()
  }
  try {
    const r = await api('/api/auth/code', { method: 'POST', body: { purpose, ...(email ? { email } : {}), ...pow } })
    arm(key, r.cooldown || 60)
    return r
  } catch (e) {
    if (e.status === 429) {
      const m = /(\d+)\s*秒/.exec(e.message || '')
      if (m) arm(key, Number(m[1]))
    }
    throw e
  }
}
