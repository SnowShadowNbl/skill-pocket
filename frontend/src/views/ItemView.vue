<script setup>
import { track } from '../composables/analytics'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { api, formatStars, formatTime, isCancelled } from '../api'
import { groupStyle, kindStyle } from '../categoryStyle'
import ImageCarousel from '../components/ImageCarousel.vue'
import CopyButton from '../components/CopyButton.vue'
import CommentList from '../components/CommentList.vue'
import RelatedItems from '../components/RelatedItems.vue'
import RatingStars from '../components/RatingStars.vue'
import { installPrompt } from '../composables/installPrompt'
import Icon from '../components/Icon.vue'
import FavoriteButton from '../components/FavoriteButton.vue'
import FolderPicker from '../components/FolderPicker.vue'
import AiTag from '../components/AiTag.vue'
import { customDims, favTree, isFav, loadFavTree } from '../composables/favorites'
import { confirmDialog } from '../composables/dialog'
import { toast } from '../composables/toast'
import UserAvatar from '../components/UserAvatar.vue'
import StatusBadge from '../components/StatusBadge.vue'
import { authState, isAdminUser, requireLogin } from '../composables/auth'
import TakedownModal from '../components/TakedownModal.vue'
import { openFeedback } from '../composables/feedback'
import { COMPARE_MAX, compareState, fromItem, inCompare, toggleCompare } from '../composables/compare'

// 加入 / 移出对比；加入后展开左下角的对比面板，方便继续去别的页面挑
function addToCompare() {
  const entry = fromItem(item.value)
  const adding = !inCompare(entry)
  toggleCompare(entry)
  if (adding && inCompare(entry)) {
    compareState.open = true
    toast(`已加入对比（${compareState.list.length}/${COMPARE_MAX}），去别的页面继续挑，或在对比面板里开始`, 'success')
  }
}

const props = defineProps({ id: String })
const route = useRoute()
const router = useRouter()
// 抽屉所在的列表页：去掉末尾的 /items/{id}（父路由可能带参数，如 /compare/:cid）
const parentPath = () => route.path.replace(/\/items\/\d+\/?$/, '') || '/'

const item = ref(null)
const error = ref('')
const panel = ref(null)
const logSec = ref(null) // v3.3 顶部「使用日志」快捷入口滚动到这里
// 打分后只刷新口碑数字，不整页重载
async function refreshRating() {
  try {
    const d = await api(`/api/items/${props.id}`)
    Object.assign(item.value, { rating_avg: d.rating_avg, rating_count: d.rating_count })
  } catch {}
}
let pollTimer
let lastFocus

const processing = computed(() => ['pending', 'running'].includes(item.value?.ai_status))
const paragraphs = computed(() => (item.value?.description || '').split(/\n\s*\n/).filter(Boolean))
const gs = computed(() => groupStyle(item.value?.category.group_code))
// 交给 AI 编程助手安装用的固定话术
// v3.3.7 按使用类型给不同的 Prompt（Skill 安装 / MCP 配置 / 模型部署 / 工具安装 / 开发接入 / Demo 运行）
const promptInfo = computed(() => installPrompt(item.value))
const prompt = computed(() => promptInfo.value?.text || '')
const isAdmin = computed(() => isAdminUser())
// 自己提交、还没上线的条目：显示审核 / 处理状态，并自动刷新
const mine = computed(() => item.value && authState.user && item.value.uploader?.id === authState.user.id)
const pendingReview = computed(() => ['awaiting', 'declined'].includes(item.value?.status))

// 分享：复制本条目的链接，对方打开直接看到详情，关闭后回到主页
async function share() {
  track('share', { item_id: item.value.id })
  const url = `${location.origin}/items/${item.value.id}`
  try {
    await navigator.clipboard.writeText(url)
  } catch {
    const ta = Object.assign(document.createElement('textarea'), { value: url })
    ta.style.cssText = 'position:fixed;opacity:0'
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    ta.remove()
  }
  toast('链接已复制，可以粘贴到聊天里发给朋友', 'success', 2600)
}

// ---- 收藏分类与备注 ----
const pickerOpen = ref(false)
const folderBtn = ref(null)
const note = ref('')
const favOn = computed(() => item.value && isFav(item.value))
const folderNames = computed(() => {
  const ids = new Set(item.value?.favorite?.folder_ids || [])
  return customDims().flatMap((d) => d.folders.filter((f) => ids.has(f.id)).map((f) => ({ ...f, dim: d.name })))
})
async function saveNote() {
  if (!item.value?.favorite || note.value.trim() === (item.value.favorite.note || '')) return
  try {
    const r = await api(`/api/favorites/${item.value.id}/note`, { method: 'PUT', body: { note: note.value } })
    item.value.favorite.note = r.note
    toast('备注已保存', 'success', 1200)
  } catch (e) {
    toast(e.message, 'error')
  }
}
async function onFavChange(on) {
  if (!on) return (item.value.favorite = null)
  const d = await api(`/api/items/${props.id}`).catch(() => null)
  if (d) item.value.favorite = d.favorite
}

const AI_STATUS = {
  pending: ['排队提炼中', 'bg-white/70 text-ink-2'],
  running: ['AI 提炼中', 'bg-brand-soft text-brand'],
  done: ['AI 已提炼', 'bg-ok-soft text-ok'],
  rule: ['规则提炼 · 未中文化', 'bg-warn-soft text-warn'],
  failed: ['AI 失败 · 已用规则兜底', 'bg-danger-soft text-danger'],
}

async function load() {
  clearTimeout(pollTimer)
  try {
    item.value = await api(`/api/items/${props.id}`)
    note.value = item.value.favorite?.note || ''
    if (item.value.favorite && !favTree.data) loadFavTree()
    error.value = ''
    if (processing.value || (item.value.status === 'awaiting' && item.value.review_state !== 'admin')) pollTimer = setTimeout(load, 2500)
  } catch (e) {
    error.value = e.message
  }
}

function close() {
  // 从列表点进来的直接后退（保留滚动位置和筛选）；直接打开链接的回到列表
  if (window.history.state?.back) router.back()
  else router.push({ path: parentPath(), query: route.query })
}

async function reextract() {
  try {
    await api(`/api/items/${props.id}/reextract`, { method: 'POST', admin: true })
    toast('已开始重新提炼')
    load()
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  }
}

const drawing = ref(false)
async function redrawCover() {
  drawing.value = true
  try {
    const r = await api(`/api/items/${props.id}/cover`, { method: 'POST', admin: true })
    item.value.cover_url = `${r.cover_url}?t=${Date.now()}`
    item.value.cover_source = 'ai'
    toast('封面已更新', 'success')
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  } finally {
    drawing.value = false
  }
}

async function remove() {
  const ok = await confirmDialog({
    title: `删除「${item.value.name}」？`,
    message: `条目和它的全部使用日志都会删除。${item.value.repo ? '\n删除后该仓库会被拉黑，自动采集不会再收录。' : ''}`,
    danger: true,
    okText: '删除',
  })
  if (!ok) return
  try {
    await api(`/api/items/${props.id}`, { method: 'DELETE', admin: true })
    toast('已删除', 'success')
    router.replace({ path: parentPath(), query: route.query })
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  }
}

function onKey(e) {
  if (e.key === 'Escape') close()
}

watch(
  () => props.id,
  async () => {
    item.value = null
    await load()
    panel.value?.scrollTo({ top: 0 })
  },
  { immediate: true },
)

onMounted(async () => {
  lastFocus = document.activeElement
  document.body.style.overflow = 'hidden'
  addEventListener('keydown', onKey)
  await nextTick()
  // 打开时把焦点放在面板上（键盘 Tab 第一下就到关闭按钮），避免关闭按钮一打开就带着焦点框
  panel.value?.focus({ preventScroll: true })
})
onBeforeUnmount(() => {
  clearTimeout(pollTimer)
  document.body.style.overflow = ''
  removeEventListener('keydown', onKey)
  lastFocus?.focus?.({ preventScroll: true })
})

// v3.3.48 原作者申请下架：已有处理中的申请就不再弹窗
const tdOpen = ref(false)
async function openTakedown() {
  if (!(await requireLogin('登录后才能申请下架'))) return
  try {
    const r = await api(`/api/items/${item.value.id}/takedown`)
    if (r.request?.status === 'pending') {
      toast('你的下架申请正在处理中', 'info')
      return
    }
  } catch {
    // 查询失败时直接打开申请框
  }
  tdOpen.value = true
}
</script>

<template>
  <div class="fixed inset-0 z-50" role="dialog" aria-modal="true" aria-labelledby="sheet-title">
    <div class="absolute inset-0 bg-ink/20 backdrop-blur-[4px]" @click="close" />

    <aside
      ref="panel"
      tabindex="-1"
      class="sheet-panel outline-none glass-strong absolute inset-x-0 bottom-0 max-h-[92vh] overflow-y-auto overscroll-contain rounded-t-[14px] shadow-[0_-24px_60px_-24px_rgb(11_47_122/0.45)] md:inset-y-0 md:right-0 md:left-auto md:max-h-none md:w-[min(820px,calc(100vw-72px))] md:rounded-l-[14px] md:rounded-tr-none"
    >
      <div class="sticky top-0 z-10 flex items-center gap-2 px-4 pt-2.5 pb-1 md:pt-4">
        <span class="mx-auto h-[5px] w-10 rounded-full bg-ink/15 md:hidden" />
        <button
          class="absolute top-2 right-3 grid h-10 w-10 cursor-pointer place-items-center rounded-full bg-white/90 text-ink-2 shadow-[0_4px_14px_-4px_rgb(15_23_42/0.35)] ring-1 ring-ink/5 backdrop-blur-md transition-[transform,background-color,color] duration-500 ease-out-expo hover:rotate-90 hover:bg-white hover:text-ink focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-brand/45 md:top-4"
          aria-label="关闭"
          @click="close"
        ><Icon name="x" :size="20" /></button>
      </div>

      <p v-if="error" class="m-5 flex items-center gap-2 rounded-2xl bg-danger-soft p-4 text-sm text-danger" role="alert"><Icon name="alert" :size="16" />{{ error }}</p>

      <div v-else-if="!item" class="space-y-3 p-5" aria-busy="true">
        <div class="skeleton-bar h-40 rounded-2xl" />
        <div class="skeleton-bar h-6 w-1/2 rounded-lg" />
        <div class="skeleton-bar h-4 w-5/6 rounded-lg" />
      </div>

      <!-- 已下线：不展示详情 -->
      <div v-else-if="item.offline" class="flex flex-col items-center px-6 pt-10 pb-14 text-center">
        <span class="grid h-16 w-16 place-items-center rounded-3xl bg-slate-200 text-slate-500"><Icon name="alert" :size="30" /></span>
        <h2 id="sheet-title" class="mt-4 text-[20px] font-bold">「{{ item.name }}」原文已下线</h2>
        <p class="mt-2 max-w-sm text-sm leading-relaxed text-ink-2">{{ item.offline_reason || 'GitHub 上的原仓库已不可用' }}，所以不再展示详情。原地址恢复后会自动重新上线。</p>
        <p v-if="item.offline_at" class="mt-1 text-xs text-mute">下线时间：{{ formatTime(item.offline_at) }}</p>
        <div class="mt-6 flex gap-2">
          <FavoriteButton v-if="item.favorited" :item="item" variant="button" />
          <button class="btn-primary" @click="close"><Icon name="home" :size="16" />去主页看看</button>
        </div>
      </div>

      <div v-else class="px-5 pt-2 pb-10 md:px-8">
        <!-- 自己提交、还在审核的条目 -->
        <div v-if="mine && pendingReview" class="mb-4 rounded-2xl border border-warn/20 bg-warn-soft/60 p-3.5">
          <StatusBadge :item="item" />
          <p class="mt-1.5 text-[12.5px] text-ink-2">{{ item.status === 'awaiting' ? '审核通过后才会公开展示，现在只有你自己能看到。' : '这个条目没有通过审核，只有你自己能看到。' }}</p>
        </div>
        <!-- 封面（有图时） -->
        <div v-if="item.cover_url" class="relative mb-5">
          <ImageCarousel :images="item.images?.length ? item.images : item.cover_url ? [item.cover_url] : []" :name="item.name" :category="item.category" />
          <AiTag v-if="item.cover_source === 'ai'" :model="item.ai_model" class="absolute top-2.5 left-2.5 bg-white/85 backdrop-blur" />
        </div>

        <div class="flex items-start gap-3.5 pr-10">
          <span
            v-if="!item.cover_url"
            class="grid h-14 w-14 shrink-0 place-items-center rounded-[10px] text-white"
            :style="{ background: `linear-gradient(135deg, ${gs.fg}, var(--color-brand-2))` }"
          ><Icon :name="gs.icon" :size="28" /></span>
          <div class="min-w-0">
            <h2 id="sheet-title" class="text-[22px] leading-tight font-bold break-all">{{ item.name }}</h2>
            <div class="mt-1.5 flex flex-wrap gap-1.5">
              <span v-if="item.kind" class="tag" :class="kindStyle(item.kind.key).cls"><Icon :name="kindStyle(item.kind.key).icon" :size="12" />{{ item.kind.name }}</span>
              <span class="tag bg-brand-soft text-brand">{{ item.category.group_name }}</span>
              <span class="tag border border-edge bg-white/70" :style="{ color: gs.fg }">{{ item.category.name }}</span>
              <span class="tag" :class="item.source === 'auto' ? 'bg-ok-soft text-ok' : 'bg-warn-soft text-warn'">{{ item.source === 'auto' ? '系统采集' : item.uploader ? `${item.uploader.nickname} 上传` : '手动上传' }}</span>
              <span v-if="item.status === 'hidden'" class="tag bg-ink text-white">已隐藏</span>
            </div>
          </div>
        </div>

        <p class="mt-4 text-[15px] leading-relaxed text-ink-2">{{ item.summary || '暂无描述' }}<AiTag v-if="item.summary && item.ai_status === 'done'" :model="item.ai_model" class="ml-1.5 align-middle" /></p>
        <div v-if="item.rank_blurb" class="mt-3 rounded-2xl border border-brand/15 bg-brand-soft/50 px-3.5 py-2.5">
          <div class="flex items-center gap-2 text-xs font-semibold text-brand"><Icon name="trend" :size="13" />榜单详解<AiTag :model="item.rank_blurb_model" class="ml-auto" /></div>
          <p class="mt-1 text-[13.5px] leading-relaxed text-ink-2">{{ item.rank_blurb }}</p>
        </div>

        <!-- v3.3 口碑：每人最近一次的好用度打分平均 -->
        <div v-if="item.rating_count" class="mt-3 inline-flex items-center gap-2 rounded-full border border-amber-200 bg-amber-50/70 px-3 py-1 text-[13px]">
          <b class="font-mono text-[15px] text-ink">{{ item.rating_avg }}</b>
          <RatingStars :model-value="item.rating_avg" :size="14" />
          <span class="text-mute">{{ item.rating_count }} 人评 · 口碑</span>
        </div>
        <dl class="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[13px] text-mute">
          <div v-if="item.stars !== null" class="flex items-center gap-1">
            <Icon name="star" :size="14" class="fill-amber-400 text-amber-400" /><dt class="sr-only">星标</dt>
            <dd><b class="text-ink">{{ formatStars(item.stars) }}</b> 星标</dd>
          </div>
          <div v-if="item.repo?.language"><dt class="sr-only">语言</dt><dd>{{ item.repo.language }}</dd></div>
          <div v-if="item.repo?.license"><dt class="sr-only">许可</dt><dd>{{ item.repo.license }}</dd></div>
          <div v-if="item.repo?.pushed_at"><dt class="inline">最近提交 </dt><dd class="inline">{{ formatTime(item.repo.pushed_at, false) }}</dd></div>
          <div><button class="inline-flex cursor-pointer items-center gap-1 text-brand hover:underline" @click="logSec?.scrollIntoView({ behavior: 'smooth', block: 'start' })"><Icon name="message" :size="13" />使用日志 {{ item.comment_count || 0 }}</button></div>
        </dl>

        <div class="mt-4 grid grid-cols-2 gap-2">
          <a v-if="item.github_url" :href="item.github_url" target="_blank" rel="noopener" class="btn-primary" @click="track('outbound', { item_id: item.id, url: item.github_url })">
            <Icon name="github" :size="18" />在 GitHub 打开
          </a>
          <CopyButton v-if="prompt" :text="prompt" :label="promptInfo.label" icon="terminal" block :title="`复制后粘贴给 Claude Code / Codex 等 AI 编程助手：${prompt}`" />
          <a v-else-if="item.homepage_url" :href="item.homepage_url" target="_blank" rel="noopener" class="btn-primary col-span-2" @click="track('outbound', { item_id: item.id, url: item.homepage_url })">
            <Icon name="external-link" :size="18" />打开主页
          </a>
          <FavoriteButton v-if="item.status === 'published'" :item="item" variant="button" @change="onFavChange" />
          <button v-if="item.status === 'published'" class="btn-glass" @click="share"><Icon name="link" :size="16" />分享</button>
          <button
            v-if="item.status === 'published'"
            class="btn-glass"
            :class="{ '!border-brand/40 !bg-brand-soft text-brand': inCompare(fromItem(item)) }"
            :aria-pressed="inCompare(fromItem(item))"
            @click="addToCompare"
          ><Icon :name="inCompare(fromItem(item)) ? 'check' : 'layers'" :size="16" />{{ inCompare(fromItem(item)) ? '已加入对比' : '加入对比' }}</button>
        </div>

        <!-- 管理员操作 -->
        <div v-if="isAdmin" class="mt-3 rounded-2xl border border-dashed border-brand/25 p-2.5">
          <p class="mb-2 flex items-center gap-1.5 px-1 text-xs font-semibold text-mute"><Icon name="shield" :size="13" />管理员</p>
          <div class="grid grid-cols-2 gap-2">
            <a :href="`/admin/content?id=${item.id}`" target="_blank" class="btn-glass btn-sm"><Icon name="pencil" :size="15" />编辑</a>
            <button v-if="item.repo" class="btn-glass btn-sm" :disabled="processing" @click="reextract"><Icon name="refresh" :size="15" />重新提炼</button>
            <button class="btn-glass btn-sm" :disabled="drawing" @click="redrawCover">
              <Icon name="sparkles" :size="15" :class="drawing ? 'animate-pulse' : ''" />{{ drawing ? 'AI 绘制中…' : 'AI 重绘封面' }}
            </button>
            <button class="btn-danger btn-sm" @click="remove"><Icon name="trash" :size="15" />删除</button>
          </div>
        </div>

        <!-- 收藏分类与备注 -->
        <section v-if="favOn && item.favorite" class="mt-4 rounded-2xl border border-edge bg-white/55 p-3.5" aria-label="我的收藏">
          <div class="flex flex-wrap items-center gap-1.5">
            <Icon name="heart" :size="14" class="fill-brand-2 text-brand-2" />
            <span class="text-[13px] font-semibold">收藏在</span>
            <span v-for="f in folderNames" :key="f.id" class="tag border border-edge bg-white/80 text-ink-2">{{ f.emoji }}{{ f.name }}</span>
            <span v-if="!folderNames.length" class="text-[13px] text-mute">未整理</span>
            <button ref="folderBtn" class="ml-auto cursor-pointer text-[13px] text-brand hover:underline" @click="pickerOpen = !pickerOpen">调整分类</button>
          </div>
          <input
            v-model="note"
            class="field mt-2.5 h-9 text-[13px] sm:h-9"
            maxlength="500"
            placeholder="写一句为什么收藏，方便以后找（失焦自动保存）"
            aria-label="收藏备注"
            @blur="saveNote"
            @keydown.enter="$event.target.blur()"
          />
          <FolderPicker :item="item" :anchor="folderBtn" :open="pickerOpen" sticky @close="pickerOpen = false" @change="(ids) => (item.favorite.folder_ids = ids)" />
        </section>

        <!-- 功能介绍 -->
        <section v-reveal class="mt-7" aria-labelledby="sec-desc">
          <div class="flex flex-wrap items-center gap-2">
            <h3 id="sec-desc" class="section-title">功能介绍</h3>
            <span class="tag" :class="AI_STATUS[item.ai_status]?.[1]">{{ AI_STATUS[item.ai_status]?.[0] }}</span>
            <AiTag v-if="item.ai_model && item.ai_status === 'done'" :model="item.ai_model" />
          </div>
          <p v-if="item.ai_error" class="mt-3 rounded-2xl bg-danger-soft p-3 text-sm text-danger">{{ item.ai_error }}</p>
          <div v-if="processing" class="mt-4 space-y-2.5" aria-busy="true">
            <div class="skeleton-bar h-3 w-full rounded-lg" />
            <div class="skeleton-bar h-3 w-5/6 rounded-lg" />
            <div class="skeleton-bar h-3 w-2/3 rounded-lg" />
          </div>
          <div v-else class="mt-3 space-y-3 text-[15px] leading-[1.75] text-ink-2">
            <p v-for="(p, i) in paragraphs" :key="i" class="break-words whitespace-pre-line">{{ p }}</p>
            <p v-if="!paragraphs.length" class="text-mute">暂无介绍</p>
          </div>
        </section>

        <!-- 安装与使用 -->
        <section v-reveal class="mt-7" aria-labelledby="sec-install">
          <h3 id="sec-install" class="section-title">安装与使用</h3>
          <ol v-if="item.install_steps.length" class="mt-3.5 space-y-4">
            <li v-for="(s, i) in item.install_steps" :key="i" class="flex gap-3">
              <span class="grid h-[26px] w-[26px] shrink-0 place-items-center rounded-[10px] bg-brand text-xs font-bold text-white">{{ i + 1 }}</span>
              <div class="min-w-0 flex-1">
                <p class="mt-0.5 text-[14.5px] font-semibold">{{ s.title }}</p>
                <div v-if="s.command" class="mt-2 flex items-start gap-2 rounded-[8px] bg-code py-2.5 pr-2.5 pl-3">
                  <pre class="min-w-0 flex-1 overflow-x-auto font-mono text-[12.5px] leading-relaxed text-blue-100">{{ s.command }}</pre>
                  <CopyButton :text="s.command" dark />
                </div>
                <p v-if="s.note" class="mt-1.5 text-sm text-ink-2">{{ s.note }}</p>
              </div>
            </li>
          </ol>
          <p v-else class="mt-3 text-sm text-mute">{{ processing ? '提炼中…' : '暂无安装说明' }}</p>
        </section>

        <!-- 使用日志（v3.3 上移到安装步骤后面，原来在最底部容易被忽略） -->
        <section ref="logSec" v-reveal class="mt-7 scroll-mt-4" aria-labelledby="sec-log">
          <h3 id="sec-log" class="section-title mb-3">使用日志 <span class="ml-1 text-sm font-normal text-mute">{{ item.comment_count }}</span></h3>
          <CommentList :item-id="id" @changed="(n) => (item.comment_count = n)" @rated="refreshRating" />
        </section>

        <!-- 仓库 -->
        <section v-if="item.repo" v-reveal class="mt-7" aria-labelledby="sec-repo">
          <h3 id="sec-repo" class="section-title">仓库</h3>
          <div class="mt-3 flex items-center gap-2 rounded-[8px] border border-edge bg-white/60 py-1 pr-1 pl-3">
            <code class="min-w-0 flex-1 truncate font-mono text-xs text-ink-2">{{ item.github_url }}</code>
            <CopyButton :text="item.github_url" label="复制链接" />
          </div>
          <div class="mt-2 flex items-center gap-2 rounded-[8px] border border-edge bg-white/60 py-1 pr-1 pl-3">
            <code class="min-w-0 flex-1 truncate font-mono text-xs text-ink-2">git clone {{ item.clone_url }}</code>
            <CopyButton :text="`git clone ${item.clone_url}`" />
          </div>
          <div v-if="item.repo.topics.length" class="mt-3 flex flex-wrap gap-1.5">
            <span v-for="t in item.repo.topics" :key="t" class="tag border border-edge bg-white/60 text-ink-2">{{ t }}</span>
          </div>
        </section>

        <!-- 采集信息 -->
        <section v-reveal class="mt-7" aria-labelledby="sec-collect">
          <h3 id="sec-collect" class="section-title">采集信息</h3>
          <dl class="mt-3 grid grid-cols-2 gap-2.5 text-sm">
            <div class="glass rounded-2xl px-3.5 py-2.5"><dt class="text-xs text-mute">来源</dt><dd class="mt-0.5 font-medium">{{ item.source === 'auto' ? '系统采集' : '手动上传' }}</dd></div>
            <div v-if="item.uploader" class="glass rounded-2xl px-3.5 py-2.5"><dt class="text-xs text-mute">上传者</dt><dd class="mt-0.5 flex items-center gap-1.5 font-medium"><UserAvatar :user="item.uploader" :size="18" />{{ item.uploader.nickname }}</dd></div>
            <div class="glass rounded-2xl px-3.5 py-2.5"><dt class="text-xs text-mute">{{ item.source === 'auto' ? '采集时间' : '上传时间' }}</dt><dd class="mt-0.5 font-medium">{{ formatTime(item.collected_at) }}</dd></div>
            <div v-if="item.stars_at_collect !== null" class="glass rounded-2xl px-3.5 py-2.5"><dt class="text-xs text-mute">当时星标</dt><dd class="mt-0.5 font-medium tabular-nums">{{ item.stars_at_collect.toLocaleString() }}</dd></div>
            <div v-if="item.repo?.last_synced_at" class="glass rounded-2xl px-3.5 py-2.5"><dt class="text-xs text-mute">最近同步</dt><dd class="mt-0.5 font-medium">{{ formatTime(item.repo.last_synced_at) }}</dd></div>
          </dl>
          <ul v-if="item.rankings.length" class="mt-3 space-y-1.5 text-sm">
            <li v-for="(r, i) in item.rankings" :key="i" class="flex justify-between gap-2">
              <span>{{ formatTime(r.period_date, false) }} {{ r.category_name }}{{ { daily: '日榜', weekly: '周榜', monthly: '月榜' }[r.period] || '榜单' }}</span>
              <span>第 {{ r.rank }} 名 <span class="text-ok">+{{ r.stars_delta }}</span></span>
            </li>
          </ul>
          <p v-else class="mt-2.5 text-xs text-mute">上榜记录：暂无</p>
        </section>

        <!-- v3.3 详情页推荐 -->
        <RelatedItems v-if="item.status === 'published'" :item="item" />

        <p class="mt-8 text-center text-[13px] text-mute">
          信息有误或链接失效？<button class="cursor-pointer font-medium text-brand hover:underline" @click="openFeedback('content')">反馈给我们</button>
        </p>
        <p v-if="item.status === 'published'" class="mt-2 text-center text-[13px] text-mute">
          是这个项目的作者？<button class="cursor-pointer font-medium text-brand hover:underline" @click="openTakedown">申请下架</button>
        </p>
        <TakedownModal :open="tdOpen" :item="item" @close="tdOpen = false" />
      </div>
    </aside>
  </div>
</template>
