<script setup>
import { computed, onMounted, ref } from 'vue'
import { api, formatTime } from '../api'
import { useFinderJob } from '../composables/finder'
import { toast } from '../composables/toast'
import AiTag from './AiTag.vue'
import CandidateList from './CandidateList.vue'
import ErrorNote from './ErrorNote.vue'
import Icon from './Icon.vue'

// 长文识别：粘贴博主的推荐长文 / 贴文章链接 / 上传 .md .txt，AI 通读后找出提到的所有 Skill、模型、工具、项目
const emit = defineEmits(['manual'])
const props = defineProps({ embedded: Boolean })
const MAX = 50000
const mode = ref('paste') // paste / url
const text = ref('')
const url = ref('')
const fileInput = ref(null)
const recent = ref([])
const { job, error, errorCode, starting, start, retry, open, reset, adopt } = useFinderJob()

const STEPS = [
  ['fetch', '抓取文章'],
  ['read', 'AI 通读全文'],
  ['resolve', '对应 GitHub 仓库'],
]
const running = computed(() => job.value && (job.value.status === 'running' || (job.value.candidates || []).some((c) => c.state === 'resolving')))
const stepIndex = computed(() => STEPS.findIndex((s) => s[0] === job.value?.stage))
const steps = computed(() => (job.value?.source_url ? STEPS : STEPS.slice(1)))
const resolved = computed(() => (job.value?.candidates || []).filter((c) => c.state !== 'resolving').length)
const canSend = computed(() => (mode.value === 'paste' ? text.value.trim().length >= 20 : /\S+\.\S+/.test(url.value)))

function send() {
  if (!canSend.value) return
  start('/api/finder/text', mode.value === 'paste' ? { text: text.value } : { url: url.value.trim() })
}

async function onFile(e) {
  const f = e.target.files?.[0]
  e.target.value = ''
  if (!f) return
  if (f.size > 2 * 1024 * 1024) return toast('文件太大了（2MB 以内）', 'error')
  text.value = (await f.text()).slice(0, MAX)
  mode.value = 'paste'
}

async function loadRecent() {
  try {
    recent.value = await api('/api/finder/recent?kind=text')
  } catch {}
}

onMounted(() => !props.embedded && loadRecent())

// 首页搜索框传进来的长文 / 文章链接；或打开一个已经在跑的任务（搜索被 AI 转成逐个识别时）
function run(payload) {
  if (payload.url) { mode.value = 'url'; url.value = payload.url } else { mode.value = 'paste'; text.value = payload.text }
  send()
}
defineExpose({ run, open, reset, text })
</script>

<template>
  <div>
    <template v-if="!job && !embedded">
      <div class="glass inline-flex rounded-xl p-[3px]" role="group" aria-label="输入方式">
        <button
          v-for="m in [['paste', '粘贴正文', 'file-text'], ['url', '文章链接', 'link']]"
          :key="m[0]"
          class="flex h-8 cursor-pointer items-center gap-1.5 rounded-[5px] px-3 text-[13px] transition-colors duration-300"
          :class="mode === m[0] ? 'bg-white font-semibold text-ink shadow-sm' : 'text-ink-2 hover:text-ink'"
          :aria-pressed="mode === m[0]"
          @click="mode = m[0]"
        ><Icon :name="m[2]" :size="14" />{{ m[1] }}</button>
      </div>

      <form class="mt-3" @submit.prevent="send">
        <template v-if="mode === 'paste'">
          <label for="long-text" class="sr-only">长文正文</label>
          <textarea
            id="long-text"
            v-model="text"
            rows="10"
            class="field min-h-[220px] resize-y text-[14px] leading-relaxed"
            :maxlength="MAX"
            placeholder="把博主的推荐文章、「20 个必装 Skill」之类的清单整篇粘贴进来…"
          />
          <div class="mt-1.5 flex items-center gap-2 text-xs text-mute">
            <button type="button" class="cursor-pointer text-brand hover:underline" @click="fileInput.click()">或上传 .md / .txt 文件</button>
            <input ref="fileInput" type="file" accept=".md,.markdown,.txt,text/plain,text/markdown" class="hidden" @change="onFile" />
            <span class="ml-auto tabular-nums">{{ text.length.toLocaleString() }} / {{ MAX.toLocaleString() }} 字</span>
          </div>
        </template>
        <template v-else>
          <label for="article-url" class="sr-only">文章链接</label>
          <input id="article-url" v-model="url" class="field h-12 sm:h-12" inputmode="url" placeholder="https://mp.weixin.qq.com/s/… 或任意文章链接" autocapitalize="off" spellcheck="false" />
          <p class="mt-1.5 text-xs text-mute">部分平台需要登录或有反爬，抓不到时会提示你改为粘贴正文。</p>
        </template>
        <div class="mt-3 flex flex-wrap items-center gap-2">
          <p class="text-xs leading-relaxed text-mute">AI 会通读全文，找出提到的所有 Skill、模型、工具和项目，再逐个对应到 GitHub 仓库。<AiTag class="ml-1 align-middle" /></p>
          <button type="submit" class="btn-primary ml-auto w-full sm:w-auto" :disabled="starting || !canSend"><Icon name="sparkles" :size="16" />开始识别</button>
        </div>
      </form>

      <div v-if="recent.length" class="mt-6 border-t border-line pt-4">
        <p class="text-[13px] font-medium text-ink-2">最近识别</p>
        <ul class="mt-2 space-y-1">
          <li v-for="r in recent.slice(0, 5)" :key="r.id">
            <button class="flex w-full cursor-pointer items-center gap-2 rounded-xl px-2.5 py-2 text-left text-[13px] hover:bg-white/70" @click="open(r.id)">
              <Icon :name="r.source_url ? 'link' : 'file-text'" :size="14" class="shrink-0 text-mute" />
              <span class="min-w-0 flex-1 truncate">{{ r.source_url || r.query }}</span>
              <span class="shrink-0 text-xs text-mute">{{ r.count }} 个 · {{ formatTime(r.created_at) }}</span>
            </button>
          </li>
        </ul>
      </div>
    </template>

    <ErrorNote v-if="error" class="mt-4" :message="error" :code="errorCode" @retry="retry" />

    <div v-if="job">
      <div class="flex flex-wrap items-center gap-2">
        <p class="min-w-0 flex-1 truncate text-[13px] text-mute">
          <Icon :name="job.source_url ? 'link' : 'file-text'" :size="13" class="mr-1 inline" />{{ job.source_url || `${(job.chars || 0).toLocaleString()} 字的长文` }}
          <template v-if="job.links"> · 文中有 {{ job.links }} 个 GitHub 链接</template>
        </p>
        <button v-if="!embedded" class="btn-ghost btn-sm" @click="reset(), loadRecent()"><Icon name="refresh" :size="15" />换一篇</button>
      </div>

      <div v-if="running" class="mt-3" aria-live="polite">
        <ol class="flex flex-wrap items-center gap-2 text-[12.5px]">
          <li v-for="(s, k) in steps" :key="s[0]" class="flex items-center gap-1.5" :class="STEPS.indexOf(s) < stepIndex ? 'text-ok' : STEPS.indexOf(s) === stepIndex ? 'font-semibold text-brand' : 'text-mute'">
            <Icon :name="STEPS.indexOf(s) < stepIndex ? 'check' : STEPS.indexOf(s) === stepIndex ? 'refresh' : 'clock'" :size="13" :class="{ 'animate-spin': STEPS.indexOf(s) === stepIndex }" />{{ s[1] }}
            <Icon v-if="k < steps.length - 1" name="chevron-right" :size="13" class="text-mute" />
          </li>
        </ol>
        <p class="mt-2 text-[13px] text-ink-2">
          {{ job.message }}
          <template v-if="job.stage === 'resolve'">（{{ resolved }}/{{ job.candidates.length }}）</template>
        </p>
      </div>

      <p v-if="job.status === 'failed'" class="mt-3 flex items-center gap-2 rounded-2xl bg-danger-soft p-3 text-sm text-danger" role="alert"><Icon name="alert" :size="16" />{{ job.error || job.message }}</p>
      <p v-if="job.warning" class="mt-2 text-xs text-warn">{{ job.warning }}</p>

      <div v-if="job.stage === 'read' && !job.candidates?.length" class="mt-3 space-y-2"><div v-for="n in 4" :key="n" class="skeleton-bar h-[74px] rounded-2xl" /></div>
      <template v-else-if="job.candidates?.length">
        <p class="mt-4 mb-2 flex items-center gap-2 text-[15px] font-semibold">识别出 {{ job.candidates.length }} 个<AiTag /></p>
        <CandidateList :job-id="job.id" :candidates="job.candidates" mode="text" @manual="(v) => emit('manual', v)" @adopt="adopt" />
      </template>
      <p v-else-if="job.status === 'done'" class="panel mt-3 px-5 py-8 text-center text-sm text-ink-2">{{ job.message }}</p>
    </div>
  </div>
</template>
