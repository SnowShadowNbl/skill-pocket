<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '../api'
import Icon from './Icon.vue'
import UserAvatar from './UserAvatar.vue'

// v3.3.9 网页微信扫码：生成小程序码 → 每 2 秒轮询 → 手机微信扫码并在小程序里确认 → 通知外层（login 带令牌，bind 带结果）
const props = defineProps({ purpose: { type: String, default: 'login' } })
const emit = defineEmits(['done'])

const qr = ref(null) // { token, image, expires_in }
const status = ref('loading') // loading / pending / scanned / expired / canceled / error
const scanner = ref(null)
const error = ref('')
let timer
let seq = 0 // v3.3.18 每换一张码加一：旧码还在路上的轮询结果直接丢掉，不会把新码的状态改乱

async function create() {
  if (status.value === 'loading' && qr.value === null && seq > 0) return
  clearTimeout(timer)
  const my = ++seq
  qr.value = null
  status.value = 'loading'
  error.value = ''
  scanner.value = null
  try {
    const r = await api('/api/auth/wx/qr', { method: 'POST', body: { purpose: props.purpose } })
    if (my !== seq) return
    qr.value = r
    status.value = 'pending'
    timer = setTimeout(poll, 2000)
  } catch (e) {
    if (my !== seq) return
    status.value = 'error'
    error.value = e.message
  }
}

async function poll() {
  if (!qr.value) return
  const my = seq
  try {
    const r = await api(`/api/auth/wx/qr/${qr.value.token}`)
    if (my !== seq) return
    status.value = r.status
    scanner.value = r.scanner || scanner.value
    if (r.status === 'confirmed') {
      emit('done', r)
      return
    }
    if (r.status === 'expired' || r.status === 'canceled') return
  } catch {}
  if (my === seq) timer = setTimeout(poll, 2000)
}

onMounted(create)
onBeforeUnmount(() => clearTimeout(timer))
defineExpose({ refresh: create })
</script>

<template>
  <div class="flex flex-col items-center text-center">
    <div class="qr-box relative grid h-[200px] w-[200px] place-items-center overflow-hidden rounded-2xl border border-line bg-white p-2.5 shadow-[0_14px_30px_-20px_rgb(11_47_122/0.5)]">
      <div v-if="status === 'loading'" class="skeleton-bar h-full w-full rounded-xl" />
      <img v-else-if="qr?.image" :src="qr.image" alt="微信扫码" class="h-full w-full object-contain transition-[filter,opacity] duration-300" :class="{ 'opacity-15 blur-[2px]': status !== 'pending' }" />

      <!-- 已扫码：显示扫码的微信 -->
      <Transition name="pop">
        <div v-if="status === 'scanned'" class="absolute inset-0 grid place-items-center bg-white/70">
          <div class="flex flex-col items-center gap-2">
            <UserAvatar v-if="scanner" :user="scanner" :size="52" class="ring-4 ring-ok-soft" />
            <span v-else class="grid h-12 w-12 place-items-center rounded-full bg-ok text-white"><Icon name="check" :size="24" /></span>
            <b class="text-[14px]">已扫码</b>
            <span class="text-[12px] text-ink-2">请在手机上确认</span>
          </div>
        </div>
      </Transition>
      <!-- 过期 / 取消 / 出错：蒙层上醒目的「刷新二维码」 -->
      <div v-if="status === 'expired' || status === 'canceled' || status === 'error'" class="absolute inset-0 grid place-items-center bg-white/80 px-4">
        <span class="flex flex-col items-center gap-2.5 text-[13px] text-ink-2">
          <Icon v-if="status === 'error'" name="alert" :size="22" class="text-warn" />
          <span class="line-clamp-3">{{ status === 'expired' ? '二维码已过期' : status === 'canceled' ? '已在手机上取消' : error || '二维码加载失败' }}</span>
          <button class="btn-primary btn-sm" @click="create"><Icon name="refresh" :size="14" />刷新二维码</button>
        </span>
      </div>
      <span v-if="status === 'pending'" class="qr-scan pointer-events-none absolute inset-x-3 h-10" />
    </div>
    <p class="mt-3 flex items-center gap-1.5 text-[13.5px] text-ink-2">
      <Icon name="camera" :size="15" class="text-brand" />
      {{ purpose === 'bind' ? '用微信扫一扫，在小程序里确认绑定' : '用微信扫一扫，在小程序里确认登录' }}
    </p>
    <!-- v3.3.18 随时可以换一张新码（扫不出来、等太久、想重来） -->
    <button class="rp mt-1.5 inline-flex cursor-pointer items-center gap-1 text-[12.5px] text-mute transition-colors hover:text-brand disabled:cursor-default disabled:opacity-50" :disabled="status === 'loading'" @click="create">
      <Icon name="refresh" :size="13" :class="{ 'animate-spin': status === 'loading' }" />刷新二维码
    </button>
  </div>
</template>

<style scoped>
.qr-scan {
  top: 0;
  background: linear-gradient(180deg, transparent, rgb(30 86 214 / 0.18), transparent);
  animation: qrscan 2.4s ease-in-out infinite;
}
@keyframes qrscan {
  50% {
    top: calc(100% - 2.5rem);
  }
}
@media (prefers-reduced-motion: reduce) {
  .qr-scan {
    animation: none;
  }
}
</style>
