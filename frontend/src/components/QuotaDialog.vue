<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { authState } from '../composables/auth'
import { meta } from '../composables/meta'
import { WECHAT_BIND_REQUIRED, closeQuotaPopup, quotaPopup, settleBind } from '../composables/quota'
import { toast } from '../composables/toast'
import CopyButton from './CopyButton.vue'
import Icon from './Icon.vue'
import WxQrPanel from './WxQrPanel.vue'

// v3.3.89 额度用完：任何页面调用扣额度的接口都弹这个窗口，给出管理员微信号和名片二维码（后台「AI 与成本 → 额度」里设置）
// v3.3.91 只有邮箱的账号：同一个窗口改成「绑定微信领取免费额度」，直接扫码绑定
const contact = computed(() => meta.data?.quota_contact || {})
const email = computed(() => meta.data?.contact_email || '')
const bind = computed(() => quotaPopup.kind === WECHAT_BIND_REQUIRED)
const canQr = computed(() => !!meta.data?.wx_qr)
const free = computed(() => {
  const n = meta.data?.free_quota || 0
  return n >= 10000 && n % 10000 === 0 ? `${n / 10000} 万` : n.toLocaleString()
})
const okBtn = ref(null)

watch(
  () => quotaPopup.open,
  async (v) => {
    if (!v) return
    await nextTick()
    okBtn.value?.focus()
  },
)

function onBound(r) {
  if (r.user) authState.user = r.user
  quotaPopup.boundAt = Date.now()
  settleBind(true) // 先放行等待中的请求（自动重发刚才的操作），再关窗
  closeQuotaPopup()
  toast(`已绑定微信，领取了 ${free.value}额度`, 'success', 3200)
}
</script>

<template>
  <Teleport to="body">
    <Transition name="sheet">
      <div
        v-if="quotaPopup.open"
        class="fixed inset-0 z-[85] grid place-items-end bg-ink/25 backdrop-blur-[4px] sm:place-items-center"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="quota-title"
        @click.self="closeQuotaPopup"
        @keydown.esc="closeQuotaPopup"
      >
        <div class="sheet-panel glass-strong pb-safe w-full rounded-t-[14px] p-6 shadow-[0_-24px_60px_-24px_rgb(11_47_122/0.45)] sm:max-w-[420px] sm:rounded-[12px]">
          <div class="flex items-start gap-3">
            <span class="grid h-10 w-10 shrink-0 place-items-center rounded-2xl bg-brand-soft text-brand">
              <Icon :name="bind ? 'message' : 'alert'" :size="19" />
            </span>
            <div class="min-w-0 flex-1 pt-1">
              <h2 id="quota-title" class="text-[17px] font-bold">{{ bind ? `绑定微信领取 ${free}额度` : '额度已用完' }}</h2>
              <p class="mt-1.5 text-sm leading-relaxed text-ink-2">
                {{ bind ? (quotaPopup.reason === 'tip' ? '绑定后即可领取，还能用微信扫码登录、在小程序里同步收藏。' : '绑定后即可继续使用这个功能，也能在小程序里同步收藏。') : '暂时不能继续使用这个功能，联系管理员补充额度后即可继续。' }}
              </p>
            </div>
          </div>

          <template v-if="bind">
            <div v-if="canQr && authState.user" class="mt-5 rounded-[12px] border border-line bg-white/70 p-4">
              <WxQrPanel purpose="bind" @done="onBound" />
            </div>
            <RouterLink v-else to="/me" class="mt-5 flex items-center gap-2 rounded-[8px] bg-hover px-3 py-2.5 text-sm hover:text-brand" @click="closeQuotaPopup">
              <Icon name="user" :size="16" /><span>到「我的 → 账号」绑定微信</span>
            </RouterLink>
          </template>
          <template v-else>
            <div v-if="contact.qr || contact.wechat" class="mt-5 flex flex-col items-center gap-3 rounded-[12px] border border-line bg-white/70 p-4">
              <img v-if="contact.qr" :src="contact.qr" alt="管理员微信名片" class="h-auto w-[200px] max-w-full rounded-[8px]" />
              <div v-if="contact.wechat" class="flex w-full items-center gap-2 rounded-[8px] bg-hover px-3 py-2">
                <span class="cap shrink-0">微信</span>
                <b class="min-w-0 flex-1 truncate font-mono text-[15px] tabular-nums">{{ contact.wechat }}</b>
                <CopyButton :text="contact.wechat" label="复制微信号" />
              </div>
            </div>
            <a v-else-if="email" :href="`mailto:${email}`" class="mt-5 flex items-center gap-2 rounded-[8px] bg-hover px-3 py-2.5 text-sm hover:text-brand">
              <Icon name="mail" :size="16" /><span class="truncate">{{ email }}</span>
            </a>
          </template>

          <div class="mt-6 grid">
            <button ref="okBtn" type="button" class="btn-primary w-full justify-center" @click="closeQuotaPopup">{{ bind ? '稍后再说' : '知道了' }}</button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>
