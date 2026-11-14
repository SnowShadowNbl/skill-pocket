<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '../../api'
import Icon from '../../components/Icon.vue'
import UserAvatar from '../../components/UserAvatar.vue'

// 管理端微信扫码登录：生成小程序码 → 每 2 秒轮询 → 手机微信扫码并在小程序里确认。
//   和网页端扫码同一套接口，请求里带 admin: true；扫码的微信不是管理员时轮询返回 403 not_staff，二维码作废
const emit = defineEmits(['done'])
const qr = ref(null)
const status = ref('loading') // loading / pending / scanned / expired / canceled / not_staff / error
const scanner = ref(null)
const error = ref('')
let timer
let seq = 0

async function create() {
  clearTimeout(timer)
  const my = ++seq
  qr.value = null
  status.value = 'loading'
  error.value = ''
  scanner.value = null
  try {
    const r = await api('/api/auth/wx/qr', { method: 'POST', body: { purpose: 'login', admin: true } })
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
  } catch (e) {
    if (my !== seq) return
    if (e.code === 'not_staff') {
      status.value = 'not_staff'
      return
    }
  }
  if (my === seq) timer = setTimeout(poll, 2000)
}
onMounted(create)
onBeforeUnmount(() => {
  seq++
  clearTimeout(timer)
})
</script>

<template>
  <div class="flex flex-col items-center text-center">
    <div class="relative grid h-[200px] w-[200px] place-items-center overflow-hidden rounded-2xl border border-line bg-white p-2.5">
      <div v-if="status === 'loading'" class="skeleton h-full w-full rounded-xl" />
      <img v-else-if="qr?.image" :src="qr.image" alt="微信扫码" class="h-full w-full object-contain transition-[filter,opacity] duration-300" :class="{ 'opacity-15 blur-[2px]': status !== 'pending' }" />
      <div v-if="status === 'scanned'" class="absolute inset-0 grid place-items-center bg-white/70">
        <div class="flex flex-col items-center gap-2">
          <UserAvatar v-if="scanner" :user="scanner" :size="52" class="ring-4 ring-ok-soft" />
          <span v-else class="grid h-12 w-12 place-items-center rounded-full bg-ok text-white"><Icon name="check" :size="24" /></span>
          <b class="text-[14px]">已扫码</b><span class="text-[12px] text-ink-2">请在手机上确认</span>
        </div>
      </div>
      <div v-if="['expired', 'canceled', 'error', 'not_staff'].includes(status)" class="absolute inset-0 grid place-items-center bg-white/85 px-4">
        <span class="flex flex-col items-center gap-2.5 text-[13px] text-ink-2">
          <Icon :name="status === 'not_staff' || status === 'error' ? 'alert' : 'refresh'" :size="22" :class="status === 'not_staff' ? 'text-bad' : 'text-warn'" />
          <span class="line-clamp-3">{{ status === 'expired' ? '二维码已过期' : status === 'canceled' ? '已在手机上取消' : status === 'not_staff' ? '这个微信不是管理员，不能登录管理端' : error || '二维码加载失败' }}</span>
          <button type="button" class="btn btn-primary btn-sm" @click="create"><Icon name="refresh" :size="14" />刷新二维码</button>
        </span>
      </div>
    </div>
    <p class="mt-3 mb-0 flex items-center gap-1.5 text-[13.5px] text-ink-2"><Icon name="camera" :size="15" class="text-primary" />用微信扫一扫，在小程序里确认登录</p>
    <button type="button" class="mt-1.5 inline-flex items-center gap-1 text-[12.5px] text-mute hover:text-primary disabled:opacity-50" :disabled="status === 'loading'" @click="create"><Icon name="refresh" :size="13" />刷新二维码</button>
  </div>
</template>
