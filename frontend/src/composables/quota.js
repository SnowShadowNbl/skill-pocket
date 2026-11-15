import { reactive } from 'vue'

// v3.3.89 额度用完：任何接口返回 quota_exhausted 都弹同一个窗口（30 秒内不重复弹），
// 同一句错误提示也不再另外 toast，免得弹窗和提示条叠在一起
// v3.3.91 只有邮箱的账号用 AI 返回 wechat_bind_required：同一个窗口改成「绑定微信领取免费额度」
export const QUOTA_EXHAUSTED = 'quota_exhausted'
export const WECHAT_BIND_REQUIRED = 'wechat_bind_required'
export const quotaPopup = reactive({ open: false, kind: QUOTA_EXHAUSTED, message: '', at: 0, boundAt: 0, reason: '' }) // reason: 'tip' 主动提示（不是被拦下）

export const isQuotaCode = (code) => code === QUOTA_EXHAUSTED || code === WECHAT_BIND_REQUIRED

export function showQuotaExhausted(message = '', code = QUOTA_EXHAUSTED) {
  const now = Date.now()
  quotaPopup.message = message
  const same = quotaPopup.kind === code
  quotaPopup.kind = code
  if (quotaPopup.open || (same && now - quotaPopup.at < 30000)) {
    quotaPopup.at = now
    return
  }
  quotaPopup.at = now
  quotaPopup.open = true
}

/** 「我的」里主动点「绑定微信领取额度」：不受 30 秒限制 */
export function openBindWechat(reason = '') {
  quotaPopup.reason = reason
  quotaPopup.kind = WECHAT_BIND_REQUIRED
  quotaPopup.message = ''
  quotaPopup.at = Date.now()
  quotaPopup.open = true
}

export function closeQuotaPopup() {
  quotaPopup.open = false
  settleBind(false)
}

/** toast 用：刚弹过额度窗口、又是同一句话，就不再显示提示条 */
export function isQuotaEcho(message) {
  return !!quotaPopup.message && message === quotaPopup.message && Date.now() - quotaPopup.at < 5000
}

// v3.3.93 需要绑定微信时：请求层先等弹窗结果——绑定成功就自动重发刚才的请求（用户不用再点一遍），
// 关掉弹窗才把错误交给页面（红色提示里带「绑定微信」按钮，见 ErrorNote）
let bindWaiters = []

export function waitForBind(message = '') {
  // 每次都打开：这是用户刚做的操作，不受 30 秒限制
  Object.assign(quotaPopup, { kind: WECHAT_BIND_REQUIRED, message, at: Date.now(), open: true, reason: '' })
  return new Promise((resolve) => bindWaiters.push(resolve))
}

export function settleBind(ok) {
  const list = bindWaiters
  bindWaiters = []
  list.forEach((r) => r(ok))
}
