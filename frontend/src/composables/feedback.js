import { reactive } from 'vue'
import { track } from './analytics'

// 反馈弹窗的开关（右下角按钮、「我的反馈」、详情页都可以打开）
export const feedbackState = reactive({ open: false, category: 'bug' })

export function openFeedback(category = 'bug') {
  feedbackState.category = category
  track('feedback_open', { category })
  feedbackState.open = true
}
