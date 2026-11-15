<script setup>
import { computed } from 'vue'
import { QUOTA_EXHAUSTED, WECHAT_BIND_REQUIRED, quotaPopup, waitForBind } from '../composables/quota'
import Icon from './Icon.vue'

// v3.3.93 页面里的红色错误提示：需要绑定微信时带「绑定微信」按钮（绑好后自动重做刚才的操作），
// 额度用完时带「联系管理员」按钮（重新打开联系方式窗口）
// v3.3.94 按钮一律用主题蓝，不出现红色按钮；手机上单独一行平分铺满，桌面上靠右等宽
const props = defineProps({ message: String, code: { type: String, default: '' } })
const emit = defineEmits(['retry'])

async function bind() {
  if (await waitForBind(props.message)) emit('retry')
}
function contact() {
  Object.assign(quotaPopup, { kind: QUOTA_EXHAUSTED, message: props.message, at: Date.now(), open: true })
}
const actions = computed(() =>
  props.code === WECHAT_BIND_REQUIRED
    ? [{ label: '绑定微信', icon: 'message', run: bind }, { label: '联系管理员', icon: 'user', run: contact }]
    : props.code === QUOTA_EXHAUSTED
      ? [{ label: '联系管理员', icon: 'user', run: contact }]
      : [],
)
</script>

<template>
  <!-- 手机：按钮单独一行、按个数平分铺满；桌面：提示和按钮同一行，按钮靠右、等宽 -->
  <div class="flex flex-col gap-3 rounded-2xl bg-danger-soft p-3 text-sm sm:flex-row sm:items-center sm:px-4" role="alert">
    <p class="m-0 flex min-w-0 flex-1 items-start gap-2 text-danger"><Icon name="alert" :size="16" class="mt-0.5 shrink-0" /><span class="min-w-0 flex-1">{{ message }}</span></p>
    <div v-if="actions.length" class="grid shrink-0 gap-2 sm:flex" :style="{ gridTemplateColumns: `repeat(${actions.length}, minmax(0, 1fr))` }">
      <button v-for="a in actions" :key="a.label" type="button" class="btn-primary btn-sm w-full justify-center sm:w-[120px]" @click="a.run"><Icon :name="a.icon" :size="14" />{{ a.label }}</button>
    </div>
  </div>
</template>
