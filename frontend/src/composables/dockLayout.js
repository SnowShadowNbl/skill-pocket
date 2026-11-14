import { computed } from 'vue'
import { dock } from './dock'

// v3.3.27 手机底部浮窗（任务进度、AI 对比）统一排版，三端一致：
// - 底部导航上方是一行「停靠行」：展开的长条占左边，缩起来的小圆按钮排在同一行的右边（长条给它们让出位置），不再上下错开、互相遮挡
// - 两个都缩起来：两个小圆在同一行并排（任务在最右，对比在它左边）
// - 两个都展开：才叠成两行（任务在下，对比在上）
// - 「加入」栏始终在停靠行的上方
// 各浮窗组件自己报告是否显示（dock.taskShown / dock.compareShown），这里只算位置。电脑端不受影响。
export const ROW = 76 // 停靠行离底（底部导航上方）
export const LAYER = 64 // 每多一行往上挪
const SIDE = 12
const CIRCLE = 48
const CIRCLE_GAP = 8
const CIRCLE_LIFT = 6 // 小圆和长条垂直居中

const px = (n) => `calc(${n}px + env(safe-area-inset-bottom))`

export const dockLayout = computed(() => {
  const t = dock.taskShown
  const c = dock.compareShown
  const tBar = t && !dock.taskMini
  const cBar = c && !dock.compareMini
  const minis = [t && dock.taskMini && 'task', c && dock.compareMini && 'compare'].filter(Boolean)
  const reserve = minis.length * (CIRCLE + CIRCLE_GAP)
  const circle = (key) => {
    const i = minis.indexOf(key)
    return { right: `${SIDE + i * (CIRCLE + CIRCLE_GAP)}px`, bottom: px(ROW + CIRCLE_LIFT) }
  }
  const rows = t || c ? (tBar && cBar ? 2 : 1) : 0
  return {
    taskBar: { bottom: px(ROW), right: `${SIDE + reserve}px` },
    compareBar: { bottom: px(tBar ? ROW + LAYER : ROW), right: `${SIDE + (tBar ? 0 : reserve)}px` },
    taskCircle: circle('task'),
    compareCircle: circle('compare'),
    rows,
    joinBottom: px(ROW + LAYER * rows),
  }
})
