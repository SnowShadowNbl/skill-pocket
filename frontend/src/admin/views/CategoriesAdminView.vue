<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { api, formatTime, isCancelled } from '../../api'
import Icon from '../../components/Icon.vue'
import { confirmDialog } from '../../composables/dialog'
import { toast } from '../../composables/toast'
import ASelect from '../components/ASelect.vue'
import CategoryMergeDialog from '../components/CategoryMergeDialog.vue'
import CategorySplitDialog from '../components/CategorySplitDialog.vue'
import { onActionError } from '../composables/handled'
import { askReason } from '../composables/reason'

// 分类字典：两级（大类 → 子类），条目只能挂在子类上；可以合并、拆分，也可以让 AI 抽检条目的分类对不对
const route = useRoute()
const router = useRouter()
const TABS = [['dict', '分类'], ['audit', 'AI 抽检']]
const tab = computed(() => (route.query.tab === 'audit' ? 'audit' : 'dict'))
const setTab = (t) => router.replace({ query: { tab: t === 'dict' ? undefined : t } })

const tree = ref(null)
const health = ref({})
const thresholds = ref({ too_big: 200 })
const editing = ref(null) // { id, name, remark }
const adding = reactive({ parentId: undefined, code: '', name: '', remark: '' })
const merging = ref(null)
const splitting = ref(null)

async function load() {
  try {
    const [t, h] = await Promise.all([api('/api/categories?include_disabled=true'), api('/api/admin/categories/health')])
    tree.value = t
    thresholds.value = h.thresholds
    health.value = Object.fromEntries(h.items.map((x) => [x.id, x]))
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  }
}

async function call(fn, ok) {
  try {
    await fn()
    toast(ok, 'success')
    await load()
    return true
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
    return false
  }
}

async function toggle(c, isGroup) {
  if (c.enabled && !(await confirmDialog({
    title: `停用「${c.name}」？`,
    message: isGroup ? '停用后这个大类及其子类不再出现在筛选和 AI 判定中，已有条目不受影响。' : '停用后不再出现在筛选和 AI 判定中，已有条目不受影响。',
    okText: '停用', danger: true,
  }))) return
  call(() => api(`/api/categories/${c.id}`, { method: 'PUT', admin: true, body: { enabled: !c.enabled } }), c.enabled ? `已停用「${c.name}」` : `已启用「${c.name}」`)
}

function startEdit(c) {
  adding.parentId = undefined
  editing.value = { id: c.id, name: c.name, remark: c.remark || '' }
}
async function saveEdit() {
  const { id, ...body } = editing.value
  if (await call(() => api(`/api/categories/${id}`, { method: 'PUT', admin: true, body }), '已保存')) editing.value = null
}

function startAdd(parentId) {
  editing.value = null
  Object.assign(adding, { parentId, code: '', name: '', remark: '' })
}
async function saveAdd() {
  const body = { parent_id: adding.parentId, code: adding.code.trim(), name: adding.name.trim(), remark: adding.remark, sort: 999 }
  if (await call(() => api('/api/categories', { method: 'POST', admin: true, body }), `已新增「${body.name}」`)) adding.parentId = undefined
}

// 合并的目标可选：所有已启用的子类
const mergeOptions = computed(() => (tree.value || []).filter((g) => g.enabled).flatMap((g) => g.children.filter((c) => c.enabled).map((c) => ({ value: c.id, label: c.name, group: g.name }))))
const STATUS_TAG = { empty: ['空分类', 'tag-gray'], too_big: ['条目过多', 'tag-warn'] }

// ------------------------------------------------------------ AI 抽检
const audit = ref(null)
const auditPage = ref(1)
const auditStatus = computed(() => (['decided', 'all'].includes(route.query.status) ? route.query.status : 'open'))
const setAuditStatus = (s) => router.replace({ query: { tab: 'audit', status: s === 'open' ? undefined : s } })
const run = reactive({ category_id: '', sample: '20', busy: false })
const runOptions = computed(() => [{ value: '', label: '全部分类' }, ...mergeOptions.value])
const AUDIT_TABS = [['open', '待处理'], ['decided', '已处理'], ['all', '全部']]

async function loadAudit(more = false) {
  auditPage.value = more ? auditPage.value + 1 : 1
  try {
    const d = await api(`/api/admin/category-audit?status=${auditStatus.value}&page=${auditPage.value}&page_size=30`)
    audit.value = more ? { ...d, items: [...audit.value.items, ...d.items] } : d
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  }
}
async function startAudit() {
  run.busy = true
  try {
    const body = { sample: Math.max(1, Math.min(100, Number(run.sample) || 20)) }
    if (run.category_id) body.category_id = run.category_id
    const r = await api('/api/admin/category-audit/run', { method: 'POST', body })
    toast(`已开始抽检 ${r.sample} 个条目，进度在右下角任务栏，完成后刷新本页`, 'success')
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  } finally {
    run.busy = false
  }
}
async function decide(a, decision) {
  let reason = ''
  if (decision === 'move') {
    reason = await askReason({
      title: `把「${a.item?.name}」改到「${a.suggested.name}」？`,
      impact: `分类将从「${a.current.name}」改为「${a.suggested.name}」，并锁定分类（重新提炼时不再覆盖）`,
      templates: ['AI 建议的分类更准确', '核对后确认应归入建议分类'],
      okText: '改分类',
    })
    if (reason === null) return
  }
  try {
    await api(`/api/admin/category-audit/${a.id}/decide`, { method: 'POST', body: { decision, reason, expected_status: a.status } })
    toast(decision === 'move' ? '已改分类' : '已保持现分类', 'success')
    await loadAudit()
  } catch (e) {
    await onActionError(e, loadAudit)
  }
}
watch([tab, auditStatus], () => tab.value === 'audit' && loadAudit(), { immediate: true })
onMounted(load)
</script>

<template>
  <div>
    <div class="flex flex-wrap items-center gap-3">
      <h1 class="m-0 text-xl font-semibold">分类字典</h1>
      <div class="seg"><button v-for="t in TABS" :key="t[0]" :class="{ on: tab === t[0] }" @click="setTab(t[0])">{{ t[1] }}</button></div>
      <button v-if="tab === 'dict'" class="btn ml-auto" @click="startAdd(null)"><Icon name="plus" :size="15" />新增大类</button>
    </div>

    <template v-if="tab === 'dict'">
      <!-- 新增 -->
      <form v-if="adding.parentId !== undefined" class="card mt-5 grid gap-3.5 border-primary p-[18px] sm:grid-cols-2" @submit.prevent="saveAdd">
        <p class="m-0 font-semibold sm:col-span-2">新增{{ adding.parentId === null ? '大类' : `子类 · ${tree?.find((g) => g.id === adding.parentId)?.name}` }}</p>
        <label class="block text-[13px] text-ink-2">编码
          <input v-model="adding.code" class="input mt-1.5 font-mono" placeholder="如 model-ocr" required pattern="[a-z0-9][a-z0-9-]{1,62}" />
          <span class="mt-1 block text-xs text-mute">小写字母、数字和连字符</span>
        </label>
        <label class="block text-[13px] text-ink-2">名称<input v-model="adding.name" class="input mt-1.5" required /></label>
        <label class="block text-[13px] text-ink-2 sm:col-span-2">说明与示例<input v-model="adding.remark" class="input mt-1.5" /></label>
        <div class="flex justify-end gap-2 sm:col-span-2">
          <button type="button" class="btn" @click="adding.parentId = undefined">取消</button>
          <button class="btn btn-primary">保存</button>
        </div>
      </form>

      <div v-if="!tree" class="skeleton mt-5 h-72" />
      <div v-else class="mt-5 space-y-3.5">
        <section v-for="g in tree" :key="g.id" class="card" :class="{ 'opacity-60': !g.enabled }">
          <div class="card-hd">
            <template v-if="editing?.id === g.id">
              <input v-model="editing.name" class="input h-8 w-44" aria-label="大类名称" />
              <button class="btn btn-sm btn-primary" @click="saveEdit">保存</button>
              <button class="btn btn-sm" @click="editing = null">取消</button>
            </template>
            <template v-else>
              <h2>{{ g.name }}</h2>
              <span class="text-xs text-mute">{{ g.children.length }} 个子类 · {{ g.item_count }} 条</span>
              <span v-if="!g.enabled" class="tag tag-gray">已停用</span>
              <span class="ml-auto flex gap-1.5">
                <button class="btn btn-sm" @click="startAdd(g.id)"><Icon name="plus" :size="14" />子类</button>
                <button class="btn btn-sm" @click="startEdit(g)">改名</button>
                <button class="btn btn-sm" :class="{ 'btn-danger': g.enabled }" @click="toggle(g, true)">{{ g.enabled ? '停用' : '启用' }}</button>
              </span>
            </template>
          </div>
          <ul class="m-0 list-none p-0">
            <li v-for="c in g.children" :key="c.id" class="border-b border-line px-[18px] py-2.5 last:border-0" :class="{ 'opacity-50': !c.enabled }">
              <div v-if="editing?.id === c.id" class="flex flex-wrap gap-2">
                <input v-model="editing.name" class="input h-8 w-40" aria-label="子类名称" />
                <input v-model="editing.remark" class="input h-8 min-w-48 flex-1" aria-label="说明" />
                <button class="btn btn-sm btn-primary" @click="saveEdit">保存</button>
                <button class="btn btn-sm" @click="editing = null">取消</button>
              </div>
              <div v-else class="flex flex-wrap items-center gap-x-3 gap-y-1.5">
                <div class="min-w-0 flex-1 basis-56">
                  <span class="flex flex-wrap items-center gap-1.5">
                    <b class="font-medium">{{ c.name }}</b>
                    <span v-if="!c.enabled" class="tag tag-gray">已停用</span>
                    <span v-if="health[c.id]?.merged_into" class="tag tag-gray">已合并到「{{ health[c.id].merged_into.name }}」</span>
                    <span v-else-if="c.enabled && STATUS_TAG[health[c.id]?.status]" class="tag" :class="STATUS_TAG[health[c.id].status][1]">{{ STATUS_TAG[health[c.id].status][0] }}</span>
                  </span>
                  <span class="mt-0.5 block truncate font-mono text-xs text-mute">{{ c.code }}<template v-if="c.remark"> · <span class="font-sans">{{ c.remark }}</span></template></span>
                </div>
                <span class="text-xs whitespace-nowrap text-mute tabular-nums">
                  <template v-if="health[c.id]">已上线 {{ health[c.id].published_count }}<template v-if="health[c.id].total_count !== health[c.id].published_count"> / 共 {{ health[c.id].total_count }}</template></template><template v-else>{{ c.item_count }} 条</template>
                </span>
                <span class="flex flex-wrap gap-1.5">
                  <button class="btn btn-sm" @click="startEdit(c)">编辑</button>
                  <button v-if="c.enabled && !health[c.id]?.merged_into" class="btn btn-sm" @click="merging = c">合并</button>
                  <button v-if="c.enabled && health[c.id]?.total_count" class="btn btn-sm" @click="splitting = c">拆分</button>
                  <button class="btn btn-sm" :class="{ 'btn-danger': c.enabled }" @click="toggle(c, false)">{{ c.enabled ? '停用' : '启用' }}</button>
                </span>
              </div>
            </li>
            <li v-if="!g.children.length" class="empty">还没有子类</li>
          </ul>
        </section>
      </div>
      <CategoryMergeDialog :open="!!merging" :category="merging" :options="mergeOptions" @close="merging = null" @done="load" />
      <CategorySplitDialog :open="!!splitting" :category="splitting" @close="splitting = null" @done="load" />
    </template>

    <!-- AI 抽检 -->
    <template v-else>
      <form class="card mt-5 flex flex-wrap items-center gap-2.5 p-3.5" @submit.prevent="startAudit">
        <div class="w-[200px]"><ASelect v-model="run.category_id" :options="runOptions" label="抽检范围" searchable /></div>
        <label class="flex items-center gap-2 text-[13px] text-ink-2">抽
          <input v-model="run.sample" type="number" min="1" max="100" class="input h-9 w-20 px-2 text-center tabular-nums" aria-label="抽检数量" />个
        </label>
        <button class="btn btn-primary" :disabled="run.busy">{{ run.busy ? '启动中…' : '开始抽检' }}</button>
        <button type="button" class="btn ml-auto" @click="loadAudit()"><Icon name="refresh" :size="14" />刷新</button>
      </form>
      <section class="card mt-3.5">
        <div class="flex flex-wrap items-center gap-2 border-b border-line px-3.5 py-3">
          <div class="seg">
            <button v-for="t in AUDIT_TABS" :key="t[0]" :class="{ on: auditStatus === t[0] }" @click="setAuditStatus(t[0])">{{ t[1] }}<b v-if="audit && t[0] !== 'all' && audit.counts[t[0]]" class="ml-1 tabular-nums" :class="auditStatus === t[0] ? '' : t[0] === 'open' ? 'text-warn' : 'text-mute'">{{ audit.counts[t[0]] }}</b></button>
          </div>
        </div>
        <div v-if="!audit" class="p-3.5"><div class="skeleton h-32" /></div>
        <p v-else-if="!audit.items.length" class="empty">{{ auditStatus === 'open' ? '没有待处理的抽检结果' : '没有记录' }}</p>
        <ul v-else class="m-0 list-none divide-y divide-line p-0">
          <li v-for="a in audit.items" :key="a.id" class="px-4 py-3.5">
            <div class="flex flex-wrap items-center gap-x-2 gap-y-1">
              <RouterLink v-if="a.item" :to="{ path: '/content', query: { id: a.item.id } }" class="text-[14px] font-semibold text-ink hover:text-primary">{{ a.item.name }}</RouterLink>
              <span v-else class="text-mute">条目已删除</span>
              <span class="tag" :class="a.agree ? 'tag-ok' : 'tag-warn'">{{ a.agree ? 'AI 认为合适' : 'AI 建议调整' }}</span>
              <span v-if="a.status !== 'open'" class="tag tag-gray">{{ a.status_label }}</span>
            </div>
            <p v-if="a.item?.summary" class="m-0 mt-1 text-xs text-ink-2">{{ a.item.summary }}</p>
            <p class="m-0 mt-2 flex flex-wrap items-center gap-1.5 text-[13px]">
              <span class="tag tag-gray">{{ a.current.name }}</span>
              <template v-if="!a.agree"><Icon name="arrow-right" :size="13" class="text-mute" /><span class="tag tag-blue">{{ a.suggested.name }}</span><span v-if="a.suggested.confidence != null" class="text-xs text-mute tabular-nums">把握 {{ Math.round(a.suggested.confidence * 100) }}%</span></template>
              <span v-if="a.item?.category && a.item.category.id !== a.current.id" class="text-xs text-warn">条目现在已是「{{ a.item.category.name }}」</span>
            </p>
            <p v-if="a.suggested.reason" class="m-0 mt-1 text-xs text-ink-2">{{ a.suggested.reason }}</p>
            <p v-if="a.status !== 'open' && a.decided_by" class="m-0 mt-1 text-xs text-mute">{{ a.decided_by.label }} 于 {{ formatTime(a.decided_at) }} 处理<template v-if="a.decision_reason">：{{ a.decision_reason }}</template></p>
            <div v-if="a.status === 'open'" class="mt-2.5 flex flex-wrap justify-end gap-2">
              <button class="btn btn-sm" @click="decide(a, 'keep')">保持现分类</button>
              <button v-if="!a.agree" class="btn btn-sm btn-primary" @click="decide(a, 'move')">改到「{{ a.suggested.name }}」</button>
            </div>
          </li>
        </ul>
        <div v-if="audit" class="flex items-center border-t border-line px-[18px] py-3 text-xs text-mute">
          共 {{ audit.total }} 条
          <button v-if="audit.items.length < audit.total" class="btn btn-sm ml-auto" @click="loadAudit(true)">加载更多</button>
        </div>
      </section>
    </template>
  </div>
</template>
