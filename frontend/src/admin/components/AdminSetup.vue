<script setup>
import { ref } from 'vue'
import { api } from '../../api'
import Icon from '../../components/Icon.vue'
import { authState } from '../../composables/auth'
import { logout } from '../../composables/auth'

// 超级管理员 Admin 首次登录后：先设置登录密码，才能使用管理功能
const pw = ref('')
const pw2 = ref('')
const busy = ref(false)
const error = ref('')

async function submit() {
  error.value = ''
  if (pw.value !== pw2.value) {
    error.value = '两次输入的密码不一致'
    return
  }
  busy.value = true
  try {
    const r = await api('/api/admin-setup/password', { method: 'POST', body: { password: pw.value } })
    authState.user = r.user
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="grid min-h-dvh place-items-center px-4">
    <form class="card w-full max-w-[400px] p-8" @submit.prevent="submit">
      <span class="grid h-11 w-11 place-items-center rounded-full bg-primary-soft text-primary"><Icon name="lock" :size="20" /></span>
      <h1 class="mt-4 mb-1 text-lg font-semibold">设置 Admin 的登录密码</h1>
      <p class="mb-5 text-sm text-ink-2">这是超级管理员的首次登录。设置密码后，免密码登录会永久关闭，以后用「admin + 密码」登录。</p>
      <label class="mb-1.5 block text-[13px] text-ink-2" for="s-pw">新密码</label>
      <input id="s-pw" v-model="pw" class="input h-10" type="password" autocomplete="new-password" required />
      <p class="mt-1.5 mb-0 text-xs text-mute">至少 8 位，同时包含字母和数字</p>
      <label class="mt-4 mb-1.5 block text-[13px] text-ink-2" for="s-pw2">再输一次</label>
      <input id="s-pw2" v-model="pw2" class="input h-10" type="password" autocomplete="new-password" required />
      <p v-if="error" class="mt-4 mb-0 flex items-center gap-1.5 rounded-md bg-bad-soft px-3 py-2 text-[13px] text-bad" role="alert"><Icon name="alert" :size="15" />{{ error }}</p>
      <button class="btn btn-primary btn-lg mt-6 w-full" :disabled="busy">{{ busy ? '保存中…' : '保存密码并进入' }}</button>
      <button type="button" class="mt-3 w-full text-center text-[13px] text-mute hover:text-primary" @click="logout">退出</button>
    </form>
  </div>
</template>
