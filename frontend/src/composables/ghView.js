import { reactive } from 'vue'

// v3.3.33 首页 GitHub 面板是否正在显示：面板切走只隐藏不销毁（检索、AI 分析的过程和结果都保留，token 不白花），
// 挂到 body 上的加入栏要跟着它一起隐藏 / 出现
export const ghView = reactive({ shown: false })
