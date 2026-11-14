<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { api } from '../../api'
import { toast } from '../../composables/toast'
import { finishVerify, verifyState } from '../composables/verify'

// 高危操作二次验证：给管理员邮箱发 6 位验证码，输对后拿到短时有效的令牌。在 AdminApp 里挂一次
//   接口：POST /api/admin/verify/request { action } → 发送验证码；POST /api/admin/verify/confirm { action, code } → { token, expires_in }
const o = computed(() => verifyState.opts)
const step = ref('send') // send → code
const code = ref('')
const busy = ref(false)
const err = ref('')
const cooldown = ref(0)
const sentTo = ref('')
const input = ref(null)
let timer

watch(() => verifyState.open, async (v) => {
  if (!v) return
  step.value = 'send'
  code.value = ''
  err.value = ''
  window.addEventListener('keydown', onKey)
  await nextTick()
})
function onKey(e) {
  if (e.key === 'Escape') cancel()
}
function cancel() {
  window.removeEventListener('keydown', onKey)
  finishVerify(null)
}
function tick() {
  clearInterval(timer)
  cooldown.value = 60
  timer = setInterval(() => (--cooldown.value <= 0 ? clearInterval(timer) : null), 1000)
}
async function send() {
  busy.value = true
  err.value = ''
  try {
    const r = await api('/api/admin/verify/request', { method: 'POST', body: { action: o.value.action } })
    sentTo.value = r.email || ''
    if (r.dev_code) toast(`开发环境验证码：${r.dev_code}`, 'info', 8000)
    step.value = 'code'
    tick()
    await nextTick()
    input.value?.focus()
  } catch (e) {
    err.value = e.code === 'no_email' ? '这个账号没有绑定邮箱，暂时不能做这个操作' : e.message
  } finally {
    busy.value = false
  }
}
async function confirm() {
  if (!/^\d{6}$/.test(code.value)) return
  busy.value = true
  err.value = ''
  try {
    const r = await api('/api/admin/verify/confirm', { method: 'POST', body: { action: o.value.action, code: code.value } })
    window.removeEventListener('keydown', onKey)
    finishVerify(r.token)
  } catch (e) {
    err.value = e.message
    code.value = ''
  } finally {
    busy.value = false
  }
}
onBeforeUnmount(() => {
  clearInterval(timer)
  window.removeEventListener('keydown', onKey)
})
</script>

<template>
  <Transition name="fade">
    <div v-if="verifyState.open" class="fixed inset-0 z-[55] grid place-items-end bg-ink/35 sm:place-items-center sm:px-4" @click.self="cancel">
      <form class="card w-full rounded-b-none p-5 shadow-[0_20px_50px_-20px_rgba(15,29,51,.35)] sm:max-w-[400px] sm:rounded-b-lg sm:p-6" role="dialog" aria-modal="true" aria-label="二次验证" @submit.prevent="step === 'send' ? send() : confirm()">
        <h2 class="m-0 text-base font-semibold">{{ o.title || '二次验证' }}</h2>
        <p class="m-0 mt-2 text-[13px] text-ink-2">{{ step === 'code' && sentTo ? `验证码已发送到 ${sentTo}` : '这是高危操作，需要先验证邮箱。' }}</p>
        <template v-if="step === 'code'">
          <input ref="input" v-model="code" inputmode="numeric" autocomplete="one-time-code" maxlength="6" class="input mt-4 text-center font-mono text-lg tracking-[.4em] tabular-nums" placeholder="6 位验证码" aria-label="验证码" />
        </template>
        <p v-if="err" class="m-0 mt-3 text-[13px] text-bad">{{ err }}</p>
        <div class="mt-5 flex items-center justify-end gap-2">
          <button v-if="step === 'code'" type="button" class="btn mr-auto text-mute" :disabled="busy || cooldown > 0" @click="send">{{ cooldown > 0 ? `${cooldown} 秒后可重发` : '重新发送' }}</button>
          <button type="button" class="btn" @click="cancel">取消</button>
          <button class="btn btn-primary" :disabled="busy || (step === 'code' && code.length !== 6)">{{ busy ? '请稍候…' : step === 'send' ? '发送验证码' : '确认' }}</button>
        </div>
      </form>
    </div>
  </Transition>
</template>
