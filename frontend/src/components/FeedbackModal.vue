<script setup>
import CheckBox from './CheckBox.vue'
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { authHeaders } from '../api'
import { authState } from '../composables/auth'
import { collectDiagnostics } from '../composables/diagnostics'
import { feedbackState } from '../composables/feedback'
import { solveChallenge } from '../composables/pow'
import { toast } from '../composables/toast'
import Icon from './Icon.vue'
import VoiceButton from './VoiceButton.vue'

// 用户反馈：类别 + 描述（可语音）+ 截图 + 诊断信息；未登录也能提交（自动做人机校验）
const route = useRoute()
const CATS = [
  ['bug', 'Bug', '🐞', '功能出错、报错、点了没反应'],
  ['feature', '功能建议', '💡', '希望增加或改进的功能'],
  ['ux', '体验问题', '🎨', '界面、交互不顺手'],
  ['content', '内容问题', '📄', '条目信息错误、分类不对、链接失效'],
  ['account', '账号问题', '👤', '登录、验证码收不到'],
  ['other', '其他', '💬', ''],
]
const category = ref('bug')
const content = ref('')
const fromVoice = ref(false)
const images = ref([]) // [{file, url}]
const withDiag = ref(true)
const email = ref('')
const busy = ref('')
const done = ref(false)
const fileInput = ref(null)

const itemId = computed(() => (route.params.id ? Number(route.params.id) : null))
const canSend = computed(() => content.value.trim().length >= 2 && !busy.value)

watch(
  () => feedbackState.open,
  (v) => {
    if (!v) return
    category.value = feedbackState.category || 'bug'
    content.value = ''
    images.value.forEach((x) => URL.revokeObjectURL(x.url))
    images.value = []
    done.value = false
    withDiag.value = true
  },
)
watch(category, (c) => (withDiag.value = c === 'bug' || c === 'account'))

function onVoice(t) {
  content.value = content.value ? `${content.value.trimEnd()}${t}` : t
  fromVoice.value = true
}

function addFiles(files) {
  for (const f of files) {
    if (!f.type.startsWith('image/')) continue
    if (images.value.length >= 3) return toast('最多 3 张截图', 'error')
    if (f.size > 10 * 1024 * 1024) return toast('截图不能超过 10MB', 'error')
    images.value.push({ file: f, url: URL.createObjectURL(f) })
  }
}
function onPaste(e) {
  if (!feedbackState.open) return
  const files = [...(e.clipboardData?.files || [])].filter((f) => f.type.startsWith('image/'))
  if (files.length) addFiles(files)
}
addEventListener('paste', onPaste)
onBeforeUnmount(() => removeEventListener('paste', onPaste))

function removeImage(i) {
  URL.revokeObjectURL(images.value[i].url)
  images.value.splice(i, 1)
}

async function submit() {
  if (!canSend.value) return
  const fd = new FormData()
  fd.append('category', category.value)
  fd.append('content', content.value.trim())
  fd.append('input_type', fromVoice.value ? 'voice' : 'text')
  fd.append('page_url', location.pathname + location.search)
  if (itemId.value) fd.append('item_id', String(itemId.value))
  if (withDiag.value) fd.append('diagnostics', JSON.stringify(collectDiagnostics()))
  if (!authState.user && email.value.trim()) fd.append('contact_email', email.value.trim())
  images.value.forEach((x) => fd.append('images', x.file))
  try {
    if (!authState.user) {
      busy.value = 'pow'
      const pow = await solveChallenge()
      fd.append('pow_token', pow.pow_token)
      fd.append('pow_nonce', pow.pow_nonce)
    }
    busy.value = 'send'
    const res = await fetch('/api/feedback', { method: 'POST', body: fd, headers: authHeaders() })
    const data = await res.json().catch(() => ({}))
    if (!res.ok) throw new Error(data.detail || `提交失败（${res.status}）`)
    done.value = true
  } catch (e) {
    toast(e.message, 'error')
  } finally {
    busy.value = ''
  }
}

function close() {
  if (!busy.value) feedbackState.open = false
}
</script>

<template>
  <Teleport to="body">
    <Transition name="sheet">
      <div
        v-if="feedbackState.open"
        class="fixed inset-0 z-[72] grid place-items-end bg-ink/25 backdrop-blur-[5px] sm:place-items-center"
        role="dialog"
        aria-modal="true"
        aria-labelledby="fb-title"
        @click.self="close"
        @keydown.esc="close"
      >
        <div class="sheet-panel glass-strong pb-safe relative max-h-[92vh] w-full overflow-y-auto rounded-t-[14px] shadow-[0_-24px_60px_-24px_rgb(11_47_122/0.45)] sm:max-w-[520px] sm:rounded-[14px]">
          <div class="px-6 pt-6 pb-6 sm:px-7">
            <button class="absolute top-4 right-4 grid h-9 w-9 cursor-pointer place-items-center rounded-xl text-mute transition-all duration-300 hover:rotate-90 hover:bg-white/80" aria-label="关闭" @click="close">
              <Icon name="x" :size="18" />
            </button>

            <!-- 提交成功 -->
            <div v-if="done" class="flex flex-col items-center py-8 text-center">
              <span class="grid h-14 w-14 place-items-center rounded-2xl bg-ok-soft text-ok"><Icon name="check" :size="28" /></span>
              <h2 id="fb-title" class="mt-4 text-xl font-bold">收到了，谢谢你的反馈</h2>
              <p class="mt-2 max-w-xs text-sm leading-relaxed text-ink-2">
                {{ authState.user ? '处理进度和回复可以在「我的 → 我的反馈」里看到。' : '我们会尽快处理。登录后提交的反馈可以在「我的」里看到处理进度。' }}
              </p>
              <button class="btn-primary mt-6" @click="feedbackState.open = false">好的</button>
            </div>

            <form v-else @submit.prevent="submit">
              <h2 id="fb-title" class="flex items-center gap-2 text-[20px] font-bold"><Icon name="message" :size="20" class="text-brand" />反馈与建议</h2>
              <p class="mt-1 text-sm text-ink-2">遇到问题或有想法都可以告诉我们，可以直接说话输入</p>

              <fieldset class="mt-4">
                <legend class="sr-only">类别</legend>
                <div class="grid grid-cols-3 gap-1.5">
                  <button
                    v-for="c in CATS"
                    :key="c[0]"
                    type="button"
                    class="flex h-11 cursor-pointer items-center justify-center gap-1 rounded-xl border text-[13px] transition-all duration-200"
                    :class="category === c[0] ? 'border-brand bg-brand-soft font-semibold text-brand' : 'border-edge bg-white/60 text-ink-2 hover:bg-white'"
                    :aria-pressed="category === c[0]"
                    :title="c[3]"
                    @click="category = c[0]"
                  ><span>{{ c[2] }}</span>{{ c[1] }}</button>
                </div>
                <p class="mt-1.5 text-xs text-mute">{{ CATS.find((c) => c[0] === category)[3] }}</p>
              </fieldset>

              <label for="fb-content" class="field-label mt-3">描述</label>
              <textarea
                id="fb-content"
                v-model="content"
                rows="5"
                maxlength="5000"
                class="field resize-y rounded-2xl"
                :placeholder="category === 'bug' ? '在哪个页面、做了什么、看到了什么（报错提示也可以写上）' : '说说你的想法'"
              />
              <div class="mt-2 flex flex-wrap items-center gap-2">
                <VoiceButton @text="onVoice" />
                <button type="button" class="btn-glass" :disabled="images.length >= 3" @click="fileInput.click()"><Icon name="image" :size="16" />截图</button>
                <input ref="fileInput" type="file" accept="image/*" multiple class="hidden" @change="addFiles($event.target.files); $event.target.value = ''" />
                <span class="text-xs text-mute">可直接 Ctrl + V 粘贴截图，最多 3 张</span>
              </div>
              <div v-if="images.length" class="mt-2 flex gap-2">
                <div v-for="(img, i) in images" :key="img.url" class="relative h-20 w-20 overflow-hidden rounded-xl border border-edge">
                  <img :src="img.url" alt="截图" class="h-full w-full object-cover" />
                  <button type="button" class="absolute top-1 right-1 grid h-6 w-6 cursor-pointer place-items-center rounded-full bg-ink/70 text-white" aria-label="移除截图" @click="removeImage(i)"><Icon name="x" :size="13" /></button>
                </div>
              </div>

              <div class="mt-3 flex cursor-pointer items-start gap-2 rounded-xl bg-white/50 px-3 py-2.5 text-[13px] text-ink-2" @click="withDiag = !withDiag">
                <CheckBox :checked="withDiag" class="mt-px" label="附带诊断信息" @toggle="withDiag = !withDiag" />
                <span>附带诊断信息（当前页面、浏览器、最近的报错和失败的请求），帮助更快定位问题</span>
              </div>

              <template v-if="!authState.user">
                <label for="fb-email" class="field-label mt-3">联系邮箱（可选，方便回复你）</label>
                <input id="fb-email" v-model="email" type="email" class="field" placeholder="name@example.com" />
              </template>

              <button class="btn-primary mt-5 h-12 w-full text-[15px]" :disabled="!canSend">
                <Icon v-if="busy" name="refresh" :size="16" class="animate-spin" />
                {{ busy === 'pow' ? '安全校验中…' : busy === 'send' ? '提交中…' : '提交反馈' }}
              </button>
            </form>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>
