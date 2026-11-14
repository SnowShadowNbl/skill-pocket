import { reactive } from 'vue'
import { homeConfig, loadHomeConfig } from './homeConfig'

// v3.3 新手引导：第一次来首页弹 3 步介绍；看过（或跳过）就记在本机，首页标题旁可以再打开
const KEY = 'skp_tour_v1'
export const tourState = reactive({ open: false, step: 0 })

function seen() {
  try {
    return !!localStorage.getItem(KEY)
  } catch {
    return true
  }
}
export function openTour() {
  tourState.step = 0
  tourState.open = true
}
export function maybeShowTour() {
  if (seen()) return
  // v3.3.71 后台可以关掉新手引导（首页运营位）
  loadHomeConfig().then(() => {
    if (homeConfig.onboardingEnabled) setTimeout(openTour, 900)
  })
}
export function closeTour() {
  tourState.open = false
  try {
    localStorage.setItem(KEY, '1')
  } catch {}
}
