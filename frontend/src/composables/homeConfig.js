import { reactive } from 'vue'

// v3.3.71 首页运营位（后台「运营工具」配置）：公告横幅、搜索框轮播提示词、新手引导开关。
// 读不到时按默认：没有横幅、用内置提示词、照常弹新手引导。
export const homeConfig = reactive({ loaded: false, banner: null, searchPlaceholders: [], onboardingEnabled: true })
let pending = null

export function loadHomeConfig() {
  if (pending) return pending
  pending = fetch('/api/home-config')
    .then((r) => (r.ok ? r.json() : null))
    .then((d) => {
      if (d) {
        homeConfig.banner = d.banner || null
        homeConfig.searchPlaceholders = Array.isArray(d.search_placeholders) ? d.search_placeholders : []
        homeConfig.onboardingEnabled = d.onboarding_enabled !== false
      }
    })
    .catch(() => {})
    .finally(() => {
      homeConfig.loaded = true
    })
  return pending
}

const DISMISS_KEY = 'skillpocket.banner.dismissed'
export function bannerDismissed(id) {
  try {
    return localStorage.getItem(DISMISS_KEY) === String(id)
  } catch {
    return false
  }
}
export function dismissBanner(id) {
  try {
    localStorage.setItem(DISMISS_KEY, String(id))
  } catch {
    // 无痕模式：只在这次浏览里关掉
  }
  homeConfig.banner = null
}
