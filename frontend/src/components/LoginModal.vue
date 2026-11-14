<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { api } from '../api'
import { authState, finishLogin, setSession } from '../composables/auth'
import { loadMeta, meta } from '../composables/meta'
import { codeLabel, codeLeft, requestCode } from '../composables/codeCooldown'
import { toast } from '../composables/toast'
import EmailInput, { rememberDomain } from './EmailInput.vue'
import Icon from './Icon.vue'
import OtpInput from './OtpInput.vue'
import WxQrPanel from './WxQrPanel.vue'

// 登录 / 注册一体：
//   验证码：邮箱 → 人机校验 → 收验证码 → 输入 6 位（未注册自动注册）→ 新用户可设昵称 / 密码（可跳过）
//   密码：邮箱或 admin + 密码；忘记密码走邮箱验证码重设
const mode = ref('code') // wechat / code / password / reset（v3.3.17 微信扫码排第一并默认选中）
const step = ref('email') // email / verify / welcome
const email = ref('')
const code = ref('')
const password = ref('')
const newPassword = ref('')
const nickname = ref('')
const showPw = ref(false)
const busy = ref('') // '' / pow / send / verify / save
const error = ref('')
const otp = ref(null)

const emailOk = computed(() => /^[^\s@]+@[^\s@]+\.[A-Za-z]{2,}$/.test(email.value))
const emailLoginOn = computed(() => meta.data?.email_login !== false)
// v3.3.9 登录方式页签：服务器配好微信后多一个「微信扫码」
// v3.3.17 与小程序一致：微信登录（扫码）/ 邮箱验证码 / 邮箱密码
const MODES = computed(() => [...(meta.data?.wx_qr ? [['wechat', '微信登录']] : []), ['code', '邮箱验证码'], ['password', '邮箱密码']])
const defaultMode = () => (meta.data?.wx_qr ? 'wechat' : 'code')
// 冷却按「用途 + 邮箱」统一记，关掉再打开弹窗也还在
const codePurpose = computed(() => (mode.value === 'reset' ? 'reset' : 'login'))
const cooldown = computed(() => codeLeft(codePurpose.value, email.value))
const modeIndex = computed(() => Math.max(0, MODES.value.findIndex((m) => m[0] === mode.value)))
function onWxDone(r) {
  done(r, '登录成功')
  finishLogin(true)
}
const title = computed(() =>
  step.value === 'welcome' ? '欢迎加入 Skill Pocket' : mode.value === 'reset' ? '找回密码' : '登录 Skill Pocket',
)

watch(
  () => authState.modal.open,
  (open) => {
    if (!open) return
    loadMeta()
    mode.value = defaultMode()
    step.value = 'email'
    code.value = password.value = newPassword.value = error.value = ''
    busy.value = ''
  },
)

function close() {
  if (busy.value) return
  finishLogin(!!authState.user)
}

// 元信息晚到时：还停在默认的邮箱验证码、且服务器开了微信，就切到微信
watch(() => meta.data?.wx_qr, (on) => on && authState.modal.open && mode.value === 'code' && step.value === 'email' && !email.value && (mode.value = 'wechat'))

async function sendCode() {
  if (!emailOk.value || cooldown.value > 0 || busy.value) return
  error.value = ''
  try {
    busy.value = 'send'
    const r = await requestCode({ purpose: codePurpose.value, email: email.value, onPow: () => (busy.value = 'pow') })
    step.value = 'verify'
    code.value = ''
    if (r.dev_code) toast(`开发环境验证码：${r.dev_code}`, 'info', 8000)
    await nextTick()
    otp.value?.focus()
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = ''
  }
}

function done(r, tip) {
  rememberDomain(r.user.email || '')
  setSession(r.token, r.user)
  toast(tip, 'success', 1800)
}

async function verify() {
  if (code.value.length !== 6 || busy.value) return
  if (mode.value === 'reset') return
  busy.value = 'verify'
  error.value = ''
  try {
    const r = await api('/api/auth/login/code', { method: 'POST', body: { email: email.value, code: code.value } })
    done(r, r.is_new ? '注册成功' : '登录成功')
    if (r.is_new) {
      nickname.value = r.user.nickname
      newPassword.value = ''
      step.value = 'welcome'
    } else {
      finishLogin(true)
    }
  } catch (e) {
    error.value = e.message
    code.value = ''
    otp.value?.focus()
  } finally {
    busy.value = ''
  }
}

async function passwordLogin() {
  if (!email.value || !password.value || busy.value) return
  busy.value = 'verify'
  error.value = ''
  try {
    done(await api('/api/auth/login/password', { method: 'POST', body: { account: email.value, password: password.value } }), '登录成功')
    finishLogin(true)
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = ''
  }
}

async function resetPassword() {
  if (code.value.length !== 6 || !newPassword.value || busy.value) return
  busy.value = 'verify'
  error.value = ''
  try {
    const r = await api('/api/auth/password/reset', {
      method: 'POST',
      body: { email: email.value, code: code.value, new_password: newPassword.value },
    })
    done(r, '密码已重设，已登录')
    finishLogin(true)
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = ''
  }
}

async function saveWelcome() {
  busy.value = 'save'
  error.value = ''
  try {
    if (nickname.value.trim() && nickname.value.trim() !== authState.user.nickname) {
      authState.user = (await api('/api/auth/me', { method: 'PATCH', body: { nickname: nickname.value } })).user
    }
    if (newPassword.value) {
      await api('/api/auth/password', { method: 'POST', body: { new_password: newPassword.value } })
      authState.user.has_password = true
    }
    finishLogin(true)
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = ''
  }
}

function switchMode(m) {
  mode.value = m
  step.value = 'email'
  error.value = ''
  code.value = ''
}

function onKey(e) {
  if (e.key === 'Escape' && authState.modal.open && step.value !== 'welcome') close()
}
addEventListener('keydown', onKey)
onBeforeUnmount(() => {
  removeEventListener('keydown', onKey)
})

const sendLabel = computed(() =>
  busy.value === 'pow' ? '安全校验中…' : busy.value === 'send' ? '发送中…' : cooldown.value > 0 ? codeLabel(cooldown.value) : '获取验证码',
)
</script>

<template>
  <Teleport to="body">
    <Transition name="sheet">
      <div
        v-if="authState.modal.open"
        class="fixed inset-0 z-[75] grid place-items-end bg-ink/25 backdrop-blur-[6px] sm:place-items-center"
        role="dialog"
        aria-modal="true"
        aria-labelledby="login-title"
        @click.self="step !== 'welcome' && close()"
      >
        <div class="sheet-panel glass-strong pb-safe relative w-full overflow-hidden rounded-t-[14px] shadow-[0_-24px_60px_-24px_rgb(11_47_122/0.45)] sm:max-w-[420px] sm:rounded-[14px]">
          <div class="pointer-events-none absolute -top-24 -right-16 h-56 w-56 rounded-full bg-brand-2/20 blur-3xl" />
          <div class="pointer-events-none absolute -top-20 -left-20 h-48 w-48 rounded-full bg-brand/20 blur-3xl" />

          <div class="relative px-6 pt-6 pb-7 sm:px-8 sm:pt-8">
            <button
              v-if="step !== 'welcome'"
              class="absolute top-4 right-4 grid h-9 w-9 cursor-pointer place-items-center rounded-xl text-mute transition-all duration-300 hover:rotate-90 hover:bg-white/80"
              aria-label="关闭"
              @click="close"
            ><Icon name="x" :size="18" /></button>

            <span class="grid h-12 w-12 place-items-center rounded-2xl bg-brand text-white shadow-[0_10px_24px_-10px_rgb(30_86_214/0.7)]">
              <Icon :name="step === 'welcome' ? 'sparkles' : 'puzzle'" :size="24" />
            </span>
            <h2 id="login-title" class="mt-4 text-[22px] font-bold tracking-tight">{{ title }}</h2>
            <p class="mt-1 text-sm text-ink-2">
              <template v-if="step === 'welcome'">再花 10 秒完善一下，也可以直接跳过</template>
              <template v-else-if="authState.modal.reason">{{ authState.modal.reason }}</template>
              <template v-else-if="mode === 'reset'">用注册邮箱收验证码，设置新密码</template>
              <template v-else-if="mode === 'wechat'">没有邮箱也能用，之后可以在账号设置里绑定邮箱</template>
              <template v-else>未注册的邮箱验证后自动注册</template>
            </p>

            <!-- 方式切换 -->
            <div v-if="step !== 'welcome' && mode !== 'reset'" class="relative mt-5 grid rounded-xl bg-ink/[0.05] p-1" :style="{ gridTemplateColumns: `repeat(${MODES.length}, minmax(0, 1fr))` }" role="tablist">
              <span
                class="absolute inset-y-1 left-1 rounded-[5px] bg-white shadow-sm transition-transform duration-500 ease-out-expo"
                :style="{ width: `calc(${100 / MODES.length}% - ${8 / MODES.length}px)`, transform: `translateX(${modeIndex * 100}%)` }"
              />
              <button
                v-for="m in MODES"
                :key="m[0]"
                role="tab"
                :aria-selected="mode === m[0]"
                class="relative h-9 cursor-pointer text-sm transition-colors"
                :class="mode === m[0] ? 'font-semibold text-ink' : 'text-ink-2 hover:text-ink'"
                @click="switchMode(m[0])"
              >{{ m[1] }}</button>
            </div>

            <!-- 验证码登录 / 找回密码 -->
            <div v-if="(mode === 'code' || mode === 'reset') && step === 'email'" class="mt-5">
              <p v-if="!emailLoginOn" class="mb-3 flex items-start gap-2 rounded-xl bg-warn-soft px-3 py-2.5 text-[13px] text-warn">
                <Icon name="alert" :size="15" class="mt-0.5 shrink-0" />邮件验证码服务正在开通中，暂时请使用密码登录
              </p>
              <label for="login-email" class="sr-only">邮箱</label>
              <EmailInput id="login-email" v-model="email" autofocus @enter="sendCode" />
              <button class="btn-primary mt-3 h-12 w-full text-[15px]" :disabled="!emailOk || !!busy || cooldown > 0 || !emailLoginOn" @click="sendCode">
                <Icon v-if="busy" name="refresh" :size="16" class="animate-spin" />{{ sendLabel }}
              </button>
              <p v-if="busy === 'pow'" class="mt-2 text-center text-xs text-mute">正在做一次安全校验，防止验证码被恶意刷发…</p>
            </div>

            <div v-else-if="(mode === 'code' || mode === 'reset') && step === 'verify'" class="mt-5">
              <p class="text-[13.5px] text-ink-2">
                验证码已发送至 <b class="text-ink">{{ email }}</b>
                <button class="ml-1 cursor-pointer text-brand hover:underline" @click="step = 'email'">换个邮箱</button>
              </p>
              <OtpInput ref="otp" v-model="code" autofocus class="mt-3" :error="!!error" :disabled="busy === 'verify'" @complete="verify" />
              <template v-if="mode === 'reset'">
                <label for="reset-pw" class="field-label mt-4">新密码</label>
                <div class="relative">
                  <input id="reset-pw" v-model="newPassword" :type="showPw ? 'text' : 'password'" autocomplete="new-password" class="field h-12 pr-11 sm:h-12" placeholder="8 位以上，字母 + 数字" @keydown.enter="resetPassword" />
                  <button type="button" class="absolute top-1/2 right-2 grid h-8 w-8 -translate-y-1/2 cursor-pointer place-items-center rounded-lg text-mute hover:bg-white" :aria-label="showPw ? '隐藏密码' : '显示密码'" @click="showPw = !showPw"><Icon name="eye" :size="16" /></button>
                </div>
                <button class="btn-primary mt-3 h-12 w-full" :disabled="code.length !== 6 || !newPassword || !!busy" @click="resetPassword">{{ busy ? '提交中…' : '重设密码并登录' }}</button>
              </template>
              <div class="mt-3 flex items-center justify-between text-[13px]">
                <span class="text-mute">验证码 10 分钟内有效</span>
                <button class="cursor-pointer text-brand disabled:cursor-default disabled:text-mute" :disabled="cooldown > 0 || !!busy" @click="sendCode">
                  {{ cooldown > 0 ? codeLabel(cooldown) : '重新发送' }}
                </button>
              </div>
            </div>

            <!-- 密码登录 -->
            <form v-else-if="mode === 'password'" class="mt-5 space-y-3" @submit.prevent="passwordLogin">
              <label for="pw-account" class="sr-only">邮箱</label>
              <EmailInput id="pw-account" v-model="email" autofocus @enter="passwordLogin" />
              <div class="relative">
                <label for="pw-password" class="sr-only">密码</label>
                <input id="pw-password" v-model="password" :type="showPw ? 'text' : 'password'" autocomplete="current-password" class="field h-12 pr-11 sm:h-12" placeholder="密码" />
                <button type="button" class="absolute top-1/2 right-2 grid h-8 w-8 -translate-y-1/2 cursor-pointer place-items-center rounded-lg text-mute hover:bg-white" :aria-label="showPw ? '隐藏密码' : '显示密码'" @click="showPw = !showPw"><Icon name="eye" :size="16" /></button>
              </div>
              <button class="btn-primary h-12 w-full text-[15px]" :disabled="!email || !password || !!busy">{{ busy ? '登录中…' : '登录' }}</button>
              <div class="flex justify-between text-[13px]">
                <button type="button" class="cursor-pointer text-brand hover:underline" @click="switchMode('reset')">忘记密码？</button>
                <span class="text-mute">没设过密码？用验证码登录</span>
              </div>
            </form>

            <!-- v3.3.9 微信扫码登录（小程序码） -->
            <div v-else-if="mode === 'wechat'" class="mt-5">
              <WxQrPanel purpose="login" @done="onWxDone" />
            </div>

            <!-- 新用户欢迎 -->
            <form v-else-if="step === 'welcome'" class="mt-5 space-y-3" @submit.prevent="saveWelcome">
              <div>
                <label for="w-nick" class="field-label">昵称（别人看到的名字）</label>
                <input id="w-nick" v-model="nickname" class="field h-12 sm:h-12" maxlength="20" />
              </div>
              <div>
                <label for="w-pw" class="field-label">设置密码（可选，以后可以用密码登录）</label>
                <input id="w-pw" v-model="newPassword" type="password" autocomplete="new-password" class="field h-12 sm:h-12" placeholder="8 位以上，字母 + 数字" />
              </div>
              <div class="grid grid-cols-2 gap-2 pt-1">
                <button type="button" class="btn-glass h-12" :disabled="!!busy" @click="finishLogin(true)">跳过</button>
                <button class="btn-primary h-12" :disabled="!!busy">{{ busy ? '保存中…' : '完成' }}</button>
              </div>
            </form>

            <button v-if="mode === 'reset' && step === 'email'" class="mt-3 w-full cursor-pointer text-center text-[13px] text-brand hover:underline" @click="switchMode('password')">返回密码登录</button>

            <p v-if="error" class="mt-3 flex items-center gap-1.5 text-sm text-danger" role="alert"><Icon name="alert" :size="15" />{{ error }}</p>

            <p v-if="step !== 'welcome'" class="mt-6 text-center text-xs leading-relaxed text-mute">
              登录即表示同意
              <a href="/terms" target="_blank" class="text-ink-2 underline-offset-2 hover:text-brand hover:underline">用户协议</a> 和
              <a href="/privacy" target="_blank" class="text-ink-2 underline-offset-2 hover:text-brand hover:underline">隐私政策</a>
            </p>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>
