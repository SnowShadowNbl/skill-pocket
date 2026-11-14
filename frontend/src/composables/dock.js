import { reactive } from 'vue'

// v3.3.6 手机上的浮窗（任务进度、AI 对比）默认缩成右侧的小圆按钮，不挡页面；点一下展开，展开后可以再收起。
// 桌面端照常显示完整的浮窗。
const mq = typeof matchMedia === 'function' ? matchMedia('(max-width: 639px)') : null
// v3.3.27 taskShown / compareShown：两个浮窗各自报告当前是否显示，dockLayout.js 据此统一排位置
export const dock = reactive({ mobile: !!mq?.matches, taskMini: true, compareMini: true, taskShown: false, compareShown: false })
mq?.addEventListener?.('change', (e) => (dock.mobile = e.matches))
