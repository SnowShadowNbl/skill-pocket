<script setup>
import { computed, nextTick, ref } from 'vue'
import { api, formatTime } from '../api'
import { requireLogin } from '../composables/auth'
import { toast } from '../composables/toast'
import Icon from './Icon.vue'
import LinkImport from './LinkImport.vue'
import ManualAdd from './ManualAdd.vue'
import ScreenshotImport from './ScreenshotImport.vue'
import SearchImport from './SearchImport.vue'
import TextImport from './TextImport.vue'

// v3.0 首页搜索框的 GitHub 标签：原「新增 Skill」的四种方式合在一个输入框里，按输入自动分流——
//   仓库地址 / owner/repo → 解析收录；其他网址 → 抓文章逐个识别；长文 → 逐个识别；一句话 → AI 功能搜索；
//   图片（粘贴 / 拖入 / 相机按钮）→ 截图识别；.md / .txt → 逐个识别；不在 GitHub 上 → 手动填写。
// 一句话到底是「找一个功能」还是「一串项目名」交给 AI 在规划搜索时判断（后端会转去逐个识别）
const emit = defineEmits(['example', 'pick-file'])
const mode = ref(null) // search / link / text / image / manual
const input = ref('')
const link = ref(null)
const search = ref(null)
const text = ref(null)
const shot = ref(null)
const manual = ref(null)
const recent = ref(null)

const GH_URL = /^(https?:\/\/)?(www\.)?github\.com\/[\w.-]+\/[\w.-]+/i
const OWNER_REPO = /^[\w.-]+\/[\w.-]+$/
const ANY_URL = /^https?:\/\/\S+$/i

function detect(raw) {
  const s = raw.trim()
  if (!/\s/.test(s) && (GH_URL.test(s) || OWNER_REPO.test(s))) return 'link'
  if (ANY_URL.test(s)) return 'article'
  if (s.length >= 200 || s.split('\n').filter((x) => x.trim()).length >= 3) return 'text'
  return 'search'
}

const KIND_LABEL = { search: '功能搜索', link: '仓库链接', article: '文章链接', text: '逐个识别', image: '截图识别', manual: '手动填写' }
const shown = ref('') // 识别结果标签（article 也走 text 视图）

async function run(raw, forced) {
  const s = raw.trim()
  if (!s) return
  if (!(await requireLogin('在 GitHub 上找、收录项目需要先登录'))) return
  input.value = s
  const kind = forced || detect(s)
  shown.value = kind
  mode.value = kind === 'article' ? 'text' : kind
  await nextTick()
  if (kind === 'link') {
    await link.value.run(s)
    // 只是像 owner/repo 的普通词（例如 PDF/Markdown）：解析失败就当成功能搜索
    if (!GH_URL.test(s) && !forced && link.value?.error) return run(s, 'search')
  } else if (kind === 'article') text.value.run({ url: s })
  else if (kind === 'text') text.value.run({ text: s })
  else search.value.go(s)
}

async function addFile(file) {
  if (!file) return
  if (!(await requireLogin('截图识别需要先登录'))) return
  if (file.type.startsWith('image/')) {
    // v3.3.26 从别的模式切过来时，识图组件是 v-if 新建的：先丢掉旧引用，等新组件挂好再交图片
    // （否则图片可能交给刚被销毁的组件，表现为切过去了却不开始识别）
    if (mode.value !== 'image') shot.value = null
    shown.value = 'image'
    mode.value = 'image'
    await nextTick()
    for (let i = 0; i < 40 && !shot.value; i++) await new Promise((r) => setTimeout(r, 50))
    if (!shot.value) return toast('识图组件没有准备好，请再试一次', 'error')
    shot.value.send(file)
  } else if (/\.(md|markdown|txt)$/i.test(file.name) || file.type.startsWith('text/')) {
    if (file.size > 2 * 1024 * 1024) return toast('文件太大了（2MB 以内）', 'error')
    const t = (await file.text()).slice(0, 50000)
    if (t.trim().length < 20) return toast('文件内容太短了', 'error')
    input.value = `${file.name}`
    shown.value = 'text'
    mode.value = 'text'
    await nextTick()
    text.value.run({ text: t })
  } else toast('支持图片，或 .md / .txt 文件', 'error')
}

// AI 判断这串输入是好几个项目：切到逐个识别视图，接着看同一个任务
async function onReroute(id) {
  shown.value = 'text'
  mode.value = 'text'
  await nextTick()
  text.value.open(id)
}

async function openManual(prefill = {}) {
  if (!(await requireLogin('登录后就可以收录'))) return
  const url = ANY_URL.test(input.value) && !GH_URL.test(input.value) ? input.value : ''
  shown.value = 'manual'
  mode.value = 'manual'
  await nextTick()
  manual.value.fill({ ...(url ? { homepage_url: url } : {}), ...prefill })
}

function reset() {
  mode.value = null
  shown.value = ''
  search.value?.reset()
  text.value?.reset()
  shot.value?.reset()
  link.value?.reset()
}

async function loadRecent() {
  try {
    recent.value = await api('/api/finder/recent?kind=text')
  } catch {
    recent.value = []
  }
}
loadRecent()

async function openRecent(r) {
  if (!(await requireLogin('登录后查看识别记录'))) return
  input.value = r.source_url || r.query
  shown.value = r.source_url ? 'article' : 'text'
  mode.value = 'text'
  await nextTick()
  text.value.open(r.id)
}

const busy = computed(() => !!(search.value?.running || link.value?.previewing))

// 空状态里的引导：点一下就把示例放进搜索框
const GUIDES = [
  { icon: 'camera', title: '截图识别 · Ctrl V', file: true },
  { icon: 'github', title: '贴仓库地址', ex: 'https://github.com/anthropics/skills' },
  { icon: 'sparkles', title: '一句话找功能', ex: '本地运行的中文语音合成' },
  { icon: 'link', title: '贴文章链接', ex: 'https://mp.weixin.qq.com/s/…' },
]

defineExpose({ run, addFile, reset, busy, mode })
</script>

<template>
  <section class="mt-4">
    <!-- 空状态：四种用法 -->
    <div v-if="!mode">
      <div class="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <button
          v-for="(g, i) in GUIDES"
          :key="g.title"
          v-reveal="i"
          class="rp group flex cursor-pointer items-center gap-2.5 rounded-lg border border-line bg-panel px-3 py-2.5 text-left transition-[border-color,box-shadow] duration-300 hover:border-brand hover:shadow-[0_8px_20px_-16px_rgb(30_86_214/0.8)]"
          @click="g.file ? emit('pick-file') : emit('example', g.ex)"
        >
          <span class="grid h-8 w-8 shrink-0 place-items-center rounded-md bg-brand-soft text-brand transition-transform duration-500 ease-[var(--ease-spring)] group-hover:scale-110 group-hover:-rotate-6"><Icon :name="g.icon" :size="16" /></span>
          <span class="min-w-0">
            <b class="block text-[13px] font-medium">{{ g.title }}</b>
            <span v-if="g.ex" class="block truncate font-mono text-[11px] text-mute">{{ g.ex }}</span>
          </span>
        </button>
      </div>
      <div v-if="recent?.length" class="mt-4">
        <p class="cap mb-1.5">最近识别</p>
        <ul class="panel divide-y divide-line-2 p-1">
          <li v-for="r in recent.slice(0, 5)" :key="r.id">
            <button class="flex w-full cursor-pointer items-center gap-2 rounded-md px-2.5 py-2 text-left text-[13px] transition-[background-color,transform] duration-300 hover:translate-x-[3px] hover:bg-hover" @click="openRecent(r)">
              <Icon :name="r.source_url ? 'link' : 'file-text'" :size="14" class="shrink-0 text-mute" />
              <span class="min-w-0 flex-1 truncate">{{ r.source_url || r.query }}</span>
              <span class="shrink-0 font-mono text-[11px] text-mute">{{ r.count }} 个 · {{ formatTime(r.created_at) }}</span>
            </button>
          </li>
        </ul>
      </div>
    </div>

    <template v-else>
      <!-- 识别结果：一句话可以在「功能搜索 / 逐个识别」之间切换 -->
      <div v-if="mode !== 'manual'" class="mb-3 flex flex-wrap items-center gap-2">
        <span class="cap">识别为</span>
        <span class="tag bg-brand-soft font-medium text-brand">{{ KIND_LABEL[shown] }}</span>
        <button class="btn-ghost btn-sm ml-auto" @click="reset"><Icon name="x" :size="14" />清除</button>
      </div>

      <LinkImport v-if="mode === 'link'" ref="link" />
      <SearchImport v-if="mode === 'search'" ref="search" @manual="openManual" @reroute="onReroute" />
      <TextImport v-if="mode === 'text'" ref="text" embedded @manual="openManual" />
      <ScreenshotImport v-if="mode === 'image'" ref="shot" embedded />
      <ManualAdd v-if="mode === 'manual'" ref="manual" @back="reset" />
    </template>

    <p v-if="mode !== 'manual'" class="mt-5 text-[13px] text-mute">
      不在 GitHub 上？<button class="cursor-pointer font-medium text-brand hover:underline" @click="openManual()">手动填写</button>
    </p>
  </section>
</template>
