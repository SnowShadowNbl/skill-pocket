<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../../api'
import Icon from '../../components/Icon.vue'
import { authState, finishLogin, setSession } from '../../composables/auth'
import { loadMeta, meta } from '../../composables/meta'
import { solveChallenge } from '../../composables/pow'
import AdminWxQr from './AdminWxQr.vue'

// 管理端登录：密码登录或邮箱验证码登录，登录接口与主站相同
const mode = ref('password')
onMounted(() => loadMeta())
// 服务器配好微信扫码后，多一个「微信扫码」页签（只允许管理员账号）
function onWxDone(r) {
  done(r)
}
const email = ref('')
const password = ref('')
const code = ref('')
const codeSent = ref(false)
const cooldown = ref(0)
const busy = ref('')
const error = ref('')

function done(r) {
  setSession(r.token, r.user)
  finishLogin(true)
}

async function run(kind, fn) {
  error.value = ''
  busy.value = kind
  try {
    await fn()
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = ''
  }
}

const loginPassword = () => run('login', async () => {
  const account = email.value.trim()
  if (!password.value) {
    // 超级管理员 Admin 的首次登录（服务器打开了首次登录窗口时才可用），进去后先设置密码
    if (account.toLowerCase() !== 'admin') throw new Error('请输入密码')
    done(await api('/api/auth/admin/first-login', { method: 'POST', body: { account } }))
    return
  }
  done(await api('/api/auth/login/password', { method: 'POST', body: { account, password: password.value } }))
})

const sendCode = () => run('send', async () => {
  const pow = await solveChallenge()
  await api('/api/auth/code', { method: 'POST', body: { email: email.value.trim(), purpose: 'login', ...pow } })
  codeSent.value = true
  cooldown.value = 60
  const t = setInterval(() => --cooldown.value <= 0 && clearInterval(t), 1000)
})

const loginCode = () => run('login', async () => {
  done(await api('/api/auth/login/code', { method: 'POST', body: { email: email.value.trim(), code: code.value.trim() } }))
})

function submit() {
  if (mode.value === 'password') loginPassword()
  else if (codeSent.value) loginCode()
  else sendCode()
}
const siteHost = location.host
</script>

<template>
  <div class="grid min-h-dvh lg:grid-cols-[1fr_520px]">
    <section class="hidden flex-col justify-between bg-primary p-12 text-white lg:flex">
      <div class="flex items-center gap-2.5 text-lg font-bold">
        <span class="grid h-9 w-9 place-items-center rounded-lg bg-white font-extrabold text-primary">S</span>Skill Pocket 管理端
      </div>
      <div>
        <p class="text-3xl leading-snug font-bold">审核、反馈、访客与采集，<br />都在这里处理。</p>
        <p class="mt-3 text-[15px] text-white/75">只对超级管理员和子管理员开放。登录状态与主站共用。</p>
      </div>
      <p class="text-xs text-white/60">{{ siteHost }}</p>
    </section>

    <section class="flex items-center justify-center bg-white px-6 py-12">
      <form class="w-full max-w-[360px]" @submit.prevent="submit">
        <h1 class="mb-1 text-[22px] font-bold">登录管理端</h1>
        <p class="mb-6 text-sm text-mute">{{ authState.modal.reason || '请使用管理员账号登录' }}</p>

        <div class="seg mb-5 w-full">
          <button type="button" class="flex-1" :class="{ on: mode === 'password' }" @click="(mode = 'password'), (error = '')">密码登录</button>
          <button type="button" class="flex-1" :class="{ on: mode === 'code' }" @click="(mode = 'code'), (error = '')">邮箱验证码</button>
          <button v-if="meta.data?.wx_qr" type="button" class="flex-1" :class="{ on: mode === 'wechat' }" @click="(mode = 'wechat'), (error = '')">微信扫码</button>
        </div>

        <AdminWxQr v-if="mode === 'wechat'" @done="onWxDone" />
        <template v-else>

        <label class="mb-1.5 block text-[13px] text-ink-2" for="a-email">{{ mode === 'password' ? '邮箱 / 用户名' : '邮箱' }}</label>
        <input id="a-email" v-model="email" class="input h-10" :type="mode === 'password' ? 'text' : 'email'" autocomplete="username"
          :placeholder="mode === 'password' ? '邮箱，超级管理员填 admin' : 'name@example.com'" required />

        <template v-if="mode === 'password'">
          <label class="mt-4 mb-1.5 block text-[13px] text-ink-2" for="a-pw">密码</label>
          <input id="a-pw" v-model="password" class="input h-10" type="password" autocomplete="current-password" />
        </template>
        <template v-else>
          <label class="mt-4 mb-1.5 block text-[13px] text-ink-2" for="a-code">验证码</label>
          <div class="flex gap-2">
            <input id="a-code" v-model="code" class="input h-10 tracking-[.3em]" inputmode="numeric" maxlength="6" placeholder="6 位数字" :disabled="!codeSent" />
            <button type="button" class="btn h-10 w-28 shrink-0" :disabled="!!busy || cooldown > 0 || !email" @click="sendCode">
              {{ busy === 'send' ? '发送中…' : cooldown > 0 ? `${cooldown} 秒` : codeSent ? '重新发送' : '发送验证码' }}
            </button>
          </div>
          <p v-if="codeSent" class="mt-1.5 text-xs text-ok">验证码已发送到邮箱，10 分钟内有效</p>
        </template>

        <p v-if="error" class="mt-4 flex items-center gap-1.5 rounded-md bg-bad-soft px-3 py-2 text-[13px] text-bad" role="alert"><Icon name="alert" :size="15" />{{ error }}</p>

        <button class="btn btn-primary btn-lg mt-6 w-full" :disabled="!!busy || (mode === 'code' && !codeSent)">
          {{ busy === 'login' ? '登录中…' : '登录' }}
        </button>
        </template>
        <a href="/" class="mt-4 block text-center text-[13px] text-mute hover:text-primary">返回主站</a>
      </form>
    </section>
  </div>
</template>
