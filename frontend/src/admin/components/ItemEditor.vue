<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { api, authHeaders, formatStars, formatTime, isCancelled } from '../../api'
import Icon from '../../components/Icon.vue'
import { confirmDialog } from '../../composables/dialog'
import { toast } from '../../composables/toast'
import { askReason } from '../composables/reason'
import APinDialog from './APinDialog.vue'
import ASelect from './ASelect.vue'
import AiTag from '../../components/AiTag.vue'

// 内容管理的条目弹窗：查看全部数据；修改基本信息和安装步骤；图片集（上传、排序、设为封面、下载、删除、从文档重新抓取）；删除条目
const props = defineProps({
  id: { type: Number, required: true },
  tree: { type: Array, default: () => [] },
  kinds: { type: Object, default: () => ({}) },
})
const emit = defineEmits(['close', 'changed'])
const TABS = [['basic', '基本信息'], ['images', '图片集'], ['install', '安装步骤'], ['data', '全部数据'], ['changes', '修改记录']]
const tab = ref('basic')
// 修改记录：谁在什么时候改了哪些字段（管理员、AI 提炼、批量操作、置顶……）
const changes = ref(null)
async function loadChanges(more = false) {
  const page = more ? changes.value.page + 1 : 1
  try {
    const d = await api(`/api/admin/items/${props.id}/changes?page=${page}&page_size=20`)
    changes.value = more ? { ...d, items: [...changes.value.items, ...d.items] } : d
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  }
}
watch(tab, (t) => { if (t === 'changes') loadChanges() })
const fv = (v) => (v == null || v === '' ? '—' : v === true || v === 'true' ? '是' : v === false || v === 'false' ? '否' : v)
const it = ref(null)
const form = ref(null)
const saving = ref(false)
const busy = ref('')
const fileInput = ref(null)

const FIELDS = ['name', 'summary', 'description', 'kind', 'category_id', 'homepage_url', 'status', 'rank_blurb', 'install_steps']
const kindOptions = computed(() => Object.entries(props.kinds).map(([k, v]) => ({ value: k, label: v })))
const catOptions = computed(() => props.tree.flatMap((g) => g.children.map((c) => ({ value: c.id, label: c.name, group: g.name }))))
const statusOptions = [{ value: 'published', label: '已上线（前台可见）' }, { value: 'hidden', label: '已隐藏（前台不显示）' }]
const canSetStatus = computed(() => ['published', 'hidden'].includes(it.value?.status))
const changed = computed(() => (form.value ? FIELDS.filter((k) => JSON.stringify(form.value[k]) !== JSON.stringify(orig(k))) : []))

function orig(k) {
  const v = it.value
  if (k === 'kind') return v.kind_key
  if (k === 'install_steps') return (v.install_steps || []).map((s) => ({ title: s.title || '', command: s.command || '', note: s.note || '' }))
  return v[k] ?? ''
}
function fill(d) {
  it.value = d
  form.value = Object.fromEntries(FIELDS.map((k) => [k, structuredClone(orig(k))]))
}
function fail(e) {
  if (!isCancelled(e)) toast(e.message, 'error')
}
function rowOf(d) {
  const { images, ...row } = d
  return { ...row, image_count: images.length }
}

async function load() {
  try {
    fill(await api(`/api/admin/items/${props.id}`))
  } catch (e) {
    fail(e)
    emit('close')
  }
}

async function close() {
  if (changed.value.length && !(await confirmDialog({ title: '有未保存的修改，确定关闭？', message: `修改了：${changed.value.map(label).join('、')}`, okText: '不保存，关闭', danger: true }))) return
  emit('close')
}
async function unlock(fields) {
  try {
    await api(`/api/items/${props.id}/unlock`, { method: 'POST', body: { fields } })
    await load()
    toast(`已解锁：${fields.map(label).join('、')}。点「重新提炼」可以让 AI 立即更新`, 'success')
  } catch (e) {
    fail(e)
  }
}
const LABELS = { cover_path: '图片集', name: '名称', summary: '一句话简介', description: '详细介绍', kind: '使用类型', category_id: '分类', homepage_url: '主页', status: '状态', rank_blurb: '榜单详解', install_steps: '安装步骤' }
const label = (k) => LABELS[k] || k

async function save() {
  const body = {}
  for (const k of changed.value) {
    if (k === 'status' && !canSetStatus.value) continue
    body[k] = k === 'install_steps'
      ? form.value.install_steps.filter((s) => s.title.trim()).map((s) => ({ title: s.title.trim(), command: s.command?.trim() || null, note: s.note?.trim() || null }))
      : form.value[k]
  }
  if (!Object.keys(body).length) return
  saving.value = true
  try {
    await api(`/api/items/${props.id}`, { method: 'PUT', body })
    toast('已保存。改过的字段会被锁定，重新提炼时不会被 AI 覆盖', 'success')
    await load()
    emit('changed', rowOf(it.value))
  } catch (e) {
    fail(e)
  } finally {
    saving.value = false
  }
}

async function removeItem() {
  if (!(await confirmDialog({ title: `删除「${it.value.name}」？`, message: '条目和它的评论会被删除。如果这个仓库下没有别的条目，自动采集以后也不会再收录它。此操作不能撤销。', okText: '删除', danger: true }))) return
  try {
    await api(`/api/items/${props.id}`, { method: 'DELETE' })
    toast(`已删除「${it.value.name}」`, 'success')
    emit('changed', { id: props.id, deleted: true })
    emit('close')
  } catch (e) {
    fail(e)
  }
}

async function reextract() {
  if (!(await confirmDialog({ title: '让 AI 重新提炼这个条目？', message: '重新读取 GitHub 文档、整理介绍和安装步骤、重新抓图。人工改过（锁定）的字段不会被覆盖。', okText: '重新提炼' }))) return
  try {
    await api(`/api/items/${props.id}/reextract`, { method: 'POST' })
    toast('已开始重新提炼，完成后刷新查看', 'success')
  } catch (e) {
    fail(e)
  }
}

// ---------------------------------------------------------------- 图片集
const paths = computed(() => (it.value?.images || []).map((x) => x.path))

async function setImages(list, msg) {
  busy.value = 'images'
  try {
    fill(await api(`/api/admin/items/${props.id}/images`, { method: 'PUT', body: { paths: list } }))
    emit('changed', rowOf(it.value))
    toast(msg, 'success')
  } catch (e) {
    fail(e)
  } finally {
    busy.value = ''
  }
}
function move(i, d) {
  const l = [...paths.value]
  ;[l[i], l[i + d]] = [l[i + d], l[i]]
  setImages(l, '已调整顺序')
}
function makeCover(i) {
  const l = [...paths.value]
  l.unshift(...l.splice(i, 1))
  setImages(l, '已设为封面')
}
async function removeImage(i) {
  if (!(await confirmDialog({ title: '删除这张图片？', message: i === 0 ? '这是封面，删除后第二张会成为封面。' : '', okText: '删除', danger: true }))) return
  setImages(paths.value.filter((_, k) => k !== i), '已删除图片')
}

async function upload(e) {
  const files = [...(e.target.files || [])]
  e.target.value = ''
  if (!files.length) return
  busy.value = 'upload'
  try {
    for (const file of files) {
      const fd = new FormData()
      fd.append('file', file)
      const res = await fetch(`/api/admin/items/${props.id}/images`, { method: 'POST', headers: authHeaders(), body: fd })
      const d = await res.json().catch(() => null)
      if (!res.ok) throw new Error(d?.detail || `上传失败（${res.status}）`)
      fill(d)
    }
    emit('changed', rowOf(it.value))
    toast(`已上传 ${files.length} 张图片`, 'success')
  } catch (err) {
    fail(err)
  } finally {
    busy.value = ''
  }
}

async function refetch() {
  busy.value = 'refetch'
  try {
    const d = await api(`/api/admin/items/${props.id}/images/refetch`, { method: 'POST' })
    fill(d)
    emit('changed', rowOf(it.value))
    toast(d.added ? `从文档里新抓到 ${d.added} 张图片` : `文档里没有新的可用图片（检查了 ${d.tried} 张）`, d.added ? 'success' : 'info')
  } catch (e) {
    fail(e)
  } finally {
    busy.value = ''
  }
}

async function aiCover() {
  busy.value = 'ai'
  try {
    await api(`/api/items/${props.id}/cover`, { method: 'POST' })
    await load()
    emit('changed', rowOf(it.value))
    toast('AI 已重新绘制封面', 'success')
  } catch (e) {
    fail(e)
  } finally {
    busy.value = ''
  }
}

// 重新生成缩略图和动图：删掉现有文件并排到队首（不重画封面本身）
async function regenMedia() {
  const reason = await askReason({ title: `重新生成「${it.value.name}」的缩略图和动图`, impact: '会删掉现有文件，并插到队首重新生成', templates: ['封面显示不对，重新生成', '封面样式更新后重建'], okText: '重新生成' })
  if (reason === null) return
  busy.value = 'regen'
  try {
    const r = await api(`/api/admin/items/${props.id}/regenerate-cover`, { method: 'POST', body: { kind: 'all', reason } })
    toast(`已排队，队列共 ${r.queue_length} 个`, 'success')
  } catch (e) {
    fail(e)
  } finally {
    busy.value = ''
  }
}

const fileName = (p) => p.split('/').pop()

// ---------------------------------------------------------------- 首页置顶
const pinOpen = ref(false)
const PIN_TAG = { active: 'tag-blue', scheduled: 'tag-warn', expired: 'tag-gray' }
function onPinSaved(row) {
  it.value = { ...it.value, pin_weight: row.pin_weight, pin: row.pin }
  emit('changed', { ...rowOf(it.value), pin_weight: row.pin_weight, pin: row.pin })
}

// ---------------------------------------------------------------- 安装步骤
function addStep() {
  form.value.install_steps.push({ title: '', command: '', note: '' })
}
function moveStep(i, d) {
  const l = form.value.install_steps
  ;[l[i], l[i + d]] = [l[i + d], l[i]]
}

onMounted(load)
</script>

<template>
  <Teleport to="body">
    <div class="fixed inset-0 z-40 grid place-items-center bg-ink/35 p-0 sm:p-6" @click.self="close" @keydown.esc="close">
      <div class="flex h-full w-full max-w-5xl flex-col overflow-hidden bg-white shadow-[0_24px_60px_-20px_rgba(15,29,51,.45)] sm:h-[min(860px,92vh)] sm:rounded-xl" role="dialog" aria-modal="true" aria-label="条目详情">
        <header class="flex items-center gap-3 border-b border-line px-5 py-3.5">
          <span class="h-10 w-14 shrink-0 overflow-hidden rounded-md border border-line bg-subtle">
            <img v-if="it?.cover_url" :src="it.cover_url" alt="" class="h-full w-full object-cover" />
          </span>
          <div class="min-w-0">
            <p class="m-0 truncate font-semibold">{{ it?.name || '加载中…' }} <span v-if="it" class="font-normal text-mute">#{{ it.id }}</span></p>
            <p v-if="it" class="m-0 truncate text-xs text-mute">{{ it.status_label }} · {{ it.repo || '非 GitHub 条目' }}<template v-if="it.sub_path"> / {{ it.sub_path }}</template></p>
          </div>
          <button v-if="it" class="btn btn-sm ml-auto hidden sm:inline-flex" @click="pinOpen = true">
            首页置顶<span v-if="it.pin && it.pin.state !== 'none'" class="tag !h-[18px] !px-1.5 !text-[11px]" :class="PIN_TAG[it.pin.state]">{{ it.pin.state_label }} {{ it.pin.weight }}</span>
          </button>
          <a v-if="it && ['published', 'offline'].includes(it.status)" :href="`/items/${it.id}`" target="_blank" class="btn btn-sm hidden sm:inline-flex" :class="{ 'ml-auto': !it }"><Icon name="external-link" :size="14" />前台查看</a>
          <button class="btn h-9 w-9 px-0" :class="{ 'ml-auto sm:ml-0': true }" aria-label="关闭" @click="close"><Icon name="x" :size="17" /></button>
        </header>

        <nav class="flex gap-1 border-b border-line px-5" role="tablist">
          <button
            v-for="x in TABS"
            :key="x[0]"
            role="tab"
            :aria-selected="tab === x[0]"
            class="-mb-px h-11 border-b-2 px-3 text-[13.5px]"
            :class="tab === x[0] ? 'border-primary font-semibold text-primary' : 'border-transparent text-ink-2 hover:text-ink'"
            @click="tab = x[0]"
          >{{ x[1] }}<span v-if="x[0] === 'images' && it" class="ml-1 text-xs text-mute">{{ it.images.length }}</span></button>
        </nav>

        <div v-if="!it" class="flex-1 p-5"><div class="skeleton h-80" /></div>
        <div v-else class="flex-1 overflow-y-auto px-5 py-4">
          <!-- 基本信息 -->
          <div v-if="tab === 'basic'" class="grid gap-4 md:grid-cols-2">
            <label class="block text-[13px] text-ink-2 md:col-span-2">名称<input v-model="form.name" class="input mt-1.5" maxlength="200" /></label>
            <label class="block text-[13px] text-ink-2">使用类型<ASelect v-model="form.kind" :options="kindOptions" label="使用类型" class="mt-1.5" /></label>
            <label class="block text-[13px] text-ink-2">分类<ASelect v-model="form.category_id" :options="catOptions" label="分类" searchable class="mt-1.5" /></label>
            <label class="block text-[13px] text-ink-2 md:col-span-2">一句话简介<textarea v-model="form.summary" rows="2" maxlength="500" class="input mt-1.5 h-auto resize-y py-2" /></label>
            <label class="block text-[13px] text-ink-2 md:col-span-2">详细介绍（Markdown）<textarea v-model="form.description" rows="10" class="input mt-1.5 h-auto resize-y py-2 font-mono text-[12.5px] leading-relaxed" /></label>
            <label class="block text-[13px] text-ink-2">主页链接<input v-model="form.homepage_url" class="input mt-1.5" placeholder="https://" /></label>
            <label class="block text-[13px] text-ink-2">前台状态
              <ASelect v-if="canSetStatus" v-model="form.status" :options="statusOptions" label="状态" class="mt-1.5" />
              <span v-else class="input mt-1.5 flex items-center bg-subtle text-mute">{{ it.status_label }}（在审核 / 失效巡检里处理）</span>
            </label>
            <label class="block text-[13px] text-ink-2 md:col-span-2">榜单中文详解<textarea v-model="form.rank_blurb" rows="3" class="input mt-1.5 h-auto resize-y py-2" placeholder="上榜后由 AI 生成，也可以手动填写" /></label>
          </div>

          <!-- 图片集 -->
          <div v-else-if="tab === 'images'">
            <div class="flex flex-wrap items-center gap-2">
              <button class="btn btn-primary" :disabled="!!busy" @click="fileInput.click()"><Icon :name="busy === 'upload' ? 'refresh' : 'plus'" :size="14" :class="{ 'animate-spin': busy === 'upload' }" />上传图片</button>
              <input ref="fileInput" type="file" accept="image/png,image/jpeg,image/gif,image/webp" multiple class="hidden" @change="upload" />
              <button v-if="it.repo" class="btn" :disabled="!!busy" @click="refetch"><Icon :name="busy === 'refetch' ? 'refresh' : 'github'" :size="14" :class="{ 'animate-spin': busy === 'refetch' }" />从文档重新抓图</button>
              <button class="btn" :disabled="!!busy" @click="aiCover"><Icon :name="busy === 'ai' ? 'refresh' : 'sparkles'" :size="14" :class="{ 'animate-spin': busy === 'ai' }" />AI 重绘封面</button>
              <button class="btn" :disabled="!!busy" @click="regenMedia"><Icon :name="busy === 'regen' ? 'refresh' : 'image'" :size="14" :class="{ 'animate-spin': busy === 'regen' }" />重新生成缩略图和动图</button>
              <span class="ml-auto text-xs text-mute">第一张是封面；前台详情页以轮播图展示全部图片。PNG / JPG / GIF / WebP，单张不超过 8MB</span>
            </div>
            <p v-if="!it.images.length" class="empty mt-4 rounded-lg border border-dashed border-line">还没有图片，前台显示占位图</p>
            <ul v-else class="m-0 mt-4 grid list-none grid-cols-2 gap-3 p-0 md:grid-cols-3">
              <li v-for="(img, i) in it.images" :key="img.path" class="overflow-hidden rounded-lg border" :class="i === 0 ? 'border-primary ring-2 ring-primary/20' : 'border-line'">
                <a :href="img.url" target="_blank" class="block aspect-[16/10] bg-subtle"><img :src="img.url" :alt="`图片 ${i + 1}`" class="h-full w-full object-contain" loading="lazy" /></a>
                <div class="flex items-center gap-1 border-t border-line px-2 py-1.5">
                  <span v-if="i === 0" class="tag tag-blue">封面</span>
                  <button v-else class="btn btn-sm" :disabled="!!busy" @click="makeCover(i)">设为封面</button>
                  <button class="btn btn-sm ml-auto h-7 w-7 px-0" :disabled="!!busy || i === 0" aria-label="往前移" @click="move(i, -1)"><Icon name="arrow-left" :size="13" /></button>
                  <button class="btn btn-sm h-7 w-7 px-0" :disabled="!!busy || i === it.images.length - 1" aria-label="往后移" @click="move(i, 1)"><Icon name="chevron-right" :size="13" /></button>
                  <a :href="img.url" :download="fileName(img.path)" class="btn btn-sm h-7 w-7 px-0" aria-label="下载"><Icon name="download" :size="13" /></a>
                  <button class="btn btn-sm btn-danger h-7 w-7 px-0" :disabled="!!busy" aria-label="删除" @click="removeImage(i)"><Icon name="trash" :size="13" /></button>
                </div>
              </li>
            </ul>
          </div>

          <!-- 安装步骤 -->
          <div v-else-if="tab === 'install'">
            <p class="mt-0 mb-3 text-xs text-mute">前台详情页「安装方法」里按顺序显示。命令会以代码块展示、可以一键复制。</p>
            <ol class="m-0 list-none space-y-3 p-0">
              <li v-for="(s, i) in form.install_steps" :key="i" class="rounded-lg border border-line p-3">
                <div class="flex items-center gap-2">
                  <b class="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-primary-soft text-xs text-primary">{{ i + 1 }}</b>
                  <input v-model="s.title" class="input h-9" placeholder="这一步做什么" :aria-label="`第 ${i + 1} 步标题`" />
                  <button class="btn btn-sm h-8 w-8 shrink-0 px-0" :disabled="i === 0" aria-label="上移" @click="moveStep(i, -1)"><Icon name="chevron-up" :size="14" /></button>
                  <button class="btn btn-sm h-8 w-8 shrink-0 px-0" :disabled="i === form.install_steps.length - 1" aria-label="下移" @click="moveStep(i, 1)"><Icon name="chevron-down" :size="14" /></button>
                  <button class="btn btn-sm btn-danger h-8 w-8 shrink-0 px-0" aria-label="删除这一步" @click="form.install_steps.splice(i, 1)"><Icon name="trash" :size="13" /></button>
                </div>
                <textarea v-model="s.command" rows="2" class="input mt-2 h-auto resize-y py-2 font-mono text-[12.5px]" placeholder="命令（可选）" />
                <input v-model="s.note" class="input mt-2 h-9" placeholder="补充说明（可选）" />
              </li>
            </ol>
            <button class="btn mt-3" @click="addStep"><Icon name="plus" :size="14" />添加一步</button>
          </div>

          <!-- 修改记录 -->
          <div v-else-if="tab === 'changes'">
            <div v-if="!changes" class="skeleton h-40" />
            <p v-else-if="!changes.items.length" class="empty">没有修改记录</p>
            <ul v-else class="m-0 list-none p-0">
              <li v-for="c in changes.items" :key="c.id" class="border-b border-dashed border-line py-3 text-[13px] last:border-0">
                <span class="flex flex-wrap items-center gap-1.5">
                  <span class="tag tag-blue">{{ c.action_label }}</span>
                  <span class="text-xs text-ink-2">{{ c.by?.label || (c.actor === 'system' ? '系统 / AI' : '未知') }}</span>
                  <span class="text-xs text-mute">{{ formatTime(c.at) }}</span>
                </span>
                <span class="mt-1 block break-words">{{ c.summary }}</span>
                <span v-if="c.reason" class="mt-1 block border-l-2 border-line pl-2 text-xs text-ink-2">原因：{{ c.reason }}</span>
                <ul v-if="c.changes.length" class="m-0 mt-1.5 flex list-none flex-col gap-1 p-0">
                  <li v-for="x in c.changes" :key="x.field" class="rounded-md bg-subtle px-2.5 py-1.5 text-xs">
                    <span class="tag tag-gray mr-1.5">{{ x.label }}</span>
                    <span class="break-words text-mute">{{ fv(x.before) }}</span>
                    <span class="mx-1 text-mute">→</span>
                    <b class="font-medium break-words">{{ fv(x.after) }}</b>
                  </li>
                </ul>
              </li>
            </ul>
            <button v-if="changes && changes.items.length < changes.total" class="btn btn-sm mt-3" @click="loadChanges(true)">加载更多</button>
          </div>

          <!-- 全部数据 -->
          <div v-else class="grid gap-4 md:grid-cols-2">
            <section class="rounded-lg border border-line">
              <h3 class="m-0 border-b border-line px-3.5 py-2.5 text-[13px] font-semibold">收录信息</h3>
              <dl class="m-0 grid grid-cols-[96px_1fr] gap-x-3 gap-y-1.5 px-3.5 py-3 text-[13px]">
                <dt class="text-mute">状态</dt><dd class="m-0">{{ it.status_label }}<template v-if="it.review_state"> · 审核阶段 {{ it.review_state }}</template></dd>
                <dt class="text-mute">来源</dt><dd class="m-0">{{ it.source === 'auto' ? '系统采集' : '手动上传' }}<template v-if="it.uploader"> · {{ it.uploader }}</template></dd>
                <dt class="text-mute">收录时间</dt><dd class="m-0">{{ formatTime(it.collected_at) }}</dd>
                <dt class="text-mute">最近修改</dt><dd class="m-0">{{ formatTime(it.updated_at) }}</dd>
                <dt class="text-mute">分类</dt><dd class="m-0">{{ it.category_group }} / {{ it.category }}</dd>
                <dt class="text-mute">使用类型</dt><dd class="m-0">{{ it.kind?.name || '未判定' }}<template v-if="it.kind_confidence != null">（把握 {{ Math.round(it.kind_confidence * 100) }}%）</template></dd>
                <dt class="text-mute">封面来源</dt><dd class="m-0">{{ { readme: '文档截图', ai: 'AI 示意图', upload: '上传', placeholder: '占位图' }[it.cover_source] || it.cover_source }}</dd>
                <dt class="text-mute">收录时星标</dt><dd class="m-0">{{ it.stars_at_collect ?? '—' }}</dd>
                <template v-if="it.offline_reason"><dt class="text-mute">下线原因</dt><dd class="m-0 text-bad">{{ it.offline_reason }}（{{ formatTime(it.offline_at) }}）</dd></template>
                <dt class="text-mute">最近巡检</dt><dd class="m-0">{{ it.checked_at ? formatTime(it.checked_at) : '—' }}</dd>
                <template v-if="it.review_note"><dt class="text-mute">采集判定</dt><dd class="m-0">{{ it.review_note }}</dd></template>
              </dl>
            </section>
            <section class="rounded-lg border border-line">
              <h3 class="m-0 border-b border-line px-3.5 py-2.5 text-[13px] font-semibold">GitHub 仓库</h3>
              <dl v-if="it.repo_info" class="m-0 grid grid-cols-[96px_1fr] gap-x-3 gap-y-1.5 px-3.5 py-3 text-[13px]">
                <dt class="text-mute">仓库</dt><dd class="m-0 break-all"><a :href="it.github_url || it.repo_info.html_url" target="_blank" class="text-primary hover:underline">{{ it.repo_info.full_name }}</a></dd>
                <dt class="text-mute">星标 / Fork</dt><dd class="m-0">{{ formatStars(it.repo_info.stars) }} / {{ formatStars(it.repo_info.forks) }}</dd>
                <dt class="text-mute">语言</dt><dd class="m-0">{{ it.repo_info.language || '—' }}</dd>
                <dt class="text-mute">许可证</dt><dd class="m-0">{{ it.repo_info.license || '—' }}</dd>
                <dt class="text-mute">最近提交</dt><dd class="m-0">{{ it.repo_info.pushed_at ? formatTime(it.repo_info.pushed_at) : '—' }}<template v-if="it.repo_info.archived"> · <span class="text-warn">已归档</span></template></dd>
                <dt class="text-mute">默认分支</dt><dd class="m-0 font-mono text-xs">{{ it.repo_info.default_branch }}</dd>
                <dt class="text-mute">Topics</dt><dd class="m-0"><span v-for="t in it.repo_info.topics" :key="t" class="tag tag-gray mr-1 mb-1">{{ t }}</span><span v-if="!it.repo_info.topics.length">—</span></dd>
              </dl>
              <p v-else class="empty">不是 GitHub 条目</p>
            </section>
            <section class="rounded-lg border border-line">
              <h3 class="m-0 flex items-center gap-2 border-b border-line px-3.5 py-2.5 text-[13px] font-semibold">AI 处理<AiTag v-if="it.ai_model" :model="it.ai_model" /></h3>
              <dl class="m-0 grid grid-cols-[96px_1fr] gap-x-3 gap-y-1.5 px-3.5 py-3 text-[13px]">
                <dt class="text-mute">提炼状态</dt><dd class="m-0">{{ { done: 'AI 完成', rule: '规则兜底', pending: '排队中', running: '处理中', failed: '失败' }[it.ai_status] || it.ai_status }}</dd>
                <dt class="text-mute">模型</dt><dd class="m-0">{{ it.ai_model || '—' }}</dd>
                <template v-if="it.ai_error"><dt class="text-mute">错误</dt><dd class="m-0 break-words text-bad">{{ it.ai_error }}</dd></template>
                <dt class="text-mute">锁定字段</dt>
                <dd class="m-0">
                  <span v-if="!it.locked_fields.length" class="text-mute">无（重新提炼会全部更新）</span>
                  <span v-for="f in it.locked_fields" :key="f" class="tag tag-warn mr-1 mb-1 gap-1">
                    {{ label(f) }}<button class="grid h-4 w-4 place-items-center rounded hover:bg-warn/20" :aria-label="`解锁 ${label(f)}`" :title="`解锁后，重新提炼时由 AI 更新「${label(f)}」`" @click="unlock([f])"><Icon name="x" :size="11" /></button>
                  </span>
                  <button v-if="it.locked_fields.length > 1" class="btn btn-sm mt-1" @click="unlock(it.locked_fields)">全部解锁</button>
                  <p class="m-0 mt-1 text-xs text-mute">人工改过的字段会锁定，AI 重新提炼时不覆盖；解锁后下次提炼由 AI 更新。</p>
                </dd>
              </dl>
            </section>
            <section class="rounded-lg border border-line">
              <h3 class="m-0 border-b border-line px-3.5 py-2.5 text-[13px] font-semibold">搜索标签</h3>
              <div class="px-3.5 py-3">
                <span v-for="t in it.search_tags" :key="t" class="tag tag-blue mr-1 mb-1">{{ t }}</span>
                <span v-if="!it.search_tags.length" class="text-[13px] text-mute">还没有生成</span>
              </div>
            </section>
          </div>
        </div>

        <footer v-if="it" class="flex flex-wrap items-center gap-2 border-t border-line px-5 py-3">
          <button class="btn btn-danger" @click="removeItem"><Icon name="trash" :size="14" />删除条目</button>
          <button v-if="it.repo" class="btn" @click="reextract"><Icon name="refresh" :size="14" />重新提炼</button>
          <span v-if="changed.length" class="ml-auto text-xs text-warn">未保存：{{ changed.map(label).join('、') }}</span>
          <button class="btn" :class="{ 'ml-auto': !changed.length }" @click="close">关闭</button>
          <button class="btn btn-primary" :disabled="saving || !changed.length" @click="save">{{ saving ? '保存中…' : '保存修改' }}</button>
        </footer>
      </div>
    </div>
    <APinDialog :open="pinOpen" :item="it" @close="pinOpen = false" @saved="onPinSaved" />
  </Teleport>
</template>
