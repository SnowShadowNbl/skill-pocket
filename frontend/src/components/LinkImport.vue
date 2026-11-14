<script setup>
import { useItemLink } from '../composables/itemLink'
import { computed, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { api, formatStars, isCancelled } from '../api'
import { toast } from '../composables/toast'
import CheckBox from './CheckBox.vue'
import Icon from './Icon.vue'
import AiTag from './AiTag.vue'

// GitHub 链接收录（原「新增 Skill → GitHub 链接」）：首页 GitHub 搜索框识别出仓库地址 / owner/repo 后直接解析。
// 含多个 SKILL.md 的仓库会拆成多个 Skill，可以只选需要的
const itemLink = useItemLink()
const router = useRouter()
const url = ref('')
const previewing = ref(false)
const importing = ref(false)
const preview = ref(null)
const error = ref('')
const selected = ref(new Set())
const filter = ref('')

const visible = computed(() => {
  const all = preview.value?.candidates || []
  const f = filter.value.trim().toLowerCase()
  return f ? all.filter((c) => (c.name + c.sub_path + c.description).toLowerCase().includes(f)) : all
})
const selectable = computed(() => visible.value.filter((c) => !c.existing_item_id))
const allSelected = computed(() => selectable.value.length > 0 && selectable.value.every((c) => selected.value.has(c.sub_path)))

async function run(u) {
  url.value = u.trim()
  if (!url.value) return
  previewing.value = true
  error.value = ''
  preview.value = null
  filter.value = ''
  try {
    preview.value = await api('/api/import/preview', { method: 'POST', body: { url: url.value } })
    // 单个条目默认勾选；monorepo 默认不勾，让用户挑
    const fresh = preview.value.candidates.filter((c) => !c.existing_item_id)
    selected.value = new Set(fresh.length === 1 ? [fresh[0].sub_path] : [])
  } catch (e) {
    if (!isCancelled(e)) error.value = e.message
  } finally {
    previewing.value = false
  }
}

function toggle(c) {
  const s = new Set(selected.value)
  s.has(c.sub_path) ? s.delete(c.sub_path) : s.add(c.sub_path)
  selected.value = s
}

function toggleAll() {
  const s = new Set(selected.value)
  if (allSelected.value) selectable.value.forEach((c) => s.delete(c.sub_path))
  else selectable.value.forEach((c) => s.add(c.sub_path))
  selected.value = s
}

async function doImport() {
  const picks = preview.value.candidates.filter((c) => selected.value.has(c.sub_path))
  importing.value = true
  try {
    const r = await api('/api/import', { method: 'POST', body: { url: url.value, picks } })
    toast(`已加入 ${r.created.length} 个条目，正在后台提炼`, 'success', 3500)
    router.push(r.created.length === 1 ? itemLink(r.created[0]) : '/?sort=collected')
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  } finally {
    importing.value = false
  }
}

function reset() {
  preview.value = null
  error.value = ''
}

defineExpose({ run, reset, previewing, error })
</script>

<template>
  <div>
    <div v-if="previewing" class="space-y-2" aria-busy="true">
      <p class="flex items-center gap-2 text-[13px] text-ink-2"><Icon name="refresh" :size="14" class="animate-spin text-brand" />正在读取 {{ url }}</p>
      <div v-for="n in 3" :key="n" class="skeleton-bar h-[60px] rounded-lg" />
    </div>

    <p v-if="error" class="flex items-center gap-2 rounded-lg bg-danger-soft p-3 text-sm text-danger" role="alert"><Icon name="alert" :size="16" />{{ error }}</p>

    <div v-if="preview">
      <div class="flex flex-wrap items-center gap-x-3 gap-y-1">
        <a :href="preview.repo.html_url" target="_blank" rel="noopener" class="inline-flex cursor-pointer items-center gap-1 font-semibold hover:text-brand">
          {{ preview.repo.full_name }}<Icon name="external-link" :size="14" />
        </a>
        <span class="flex items-center gap-1 font-mono text-[12px] text-ink-2">★ {{ formatStars(preview.repo.stars) }}</span>
        <span v-if="preview.repo.language" class="font-mono text-[12px] text-mute">{{ preview.repo.language }}</span>
      </div>
      <p class="mt-1 text-sm leading-relaxed text-ink-2">{{ preview.repo.description }}</p>
      <p v-if="preview.repo.blocked" class="mt-3 flex items-center gap-2 rounded-lg bg-warn-soft p-3 text-sm text-warn">
        <Icon name="alert" :size="16" />这个仓库之前被删除过（已拉黑），重新导入会解除拉黑。
      </p>

      <div class="mt-4 flex flex-wrap items-center gap-2">
        <span class="text-sm font-medium">{{ preview.mode === 'skills' ? `发现 ${preview.candidates.length} 个 Skill` : '仓库条目' }}</span>
        <AiTag v-if="preview.candidates.some((c) => /[\u4e00-\u9fff]/.test(c.description || ''))" />
        <input v-if="preview.candidates.length > 6" v-model="filter" class="field h-9 w-36 sm:h-8" aria-label="筛选 Skill" placeholder="筛选" />
        <button v-if="selectable.length > 1" class="btn-ghost btn-sm ml-auto" @click="toggleAll">{{ allSelected ? '全不选' : '全选' }}</button>
      </div>

      <ul class="mt-2 max-h-[50vh] divide-y divide-line-2 overflow-y-auto rounded-lg border border-line bg-panel">
        <li v-for="c in visible" :key="c.sub_path">
          <div
            class="flex gap-3 p-3 transition-colors duration-150"
            :class="c.existing_item_id ? 'cursor-default' : 'cursor-pointer hover:bg-hover'"
            @click="!c.existing_item_id && toggle(c)"
          >
            <CheckBox class="mt-0.5" :checked="selected.has(c.sub_path)" :disabled="!!c.existing_item_id" :label="`选择 ${c.name}`" @toggle="toggle(c)" />
            <div class="min-w-0 flex-1">
              <div class="flex flex-wrap items-center gap-2">
                <span class="font-medium" :class="{ 'text-mute': c.existing_item_id }">{{ c.name }}</span>
                <code v-if="c.sub_path" class="font-mono text-xs text-mute">{{ c.sub_path }}</code>
                <RouterLink v-if="c.existing_item_id" :to="itemLink(c.existing_item_id)" class="tag cursor-pointer bg-ok-soft text-ok">已收录</RouterLink>
              </div>
              <p v-if="c.description" class="mt-0.5 line-clamp-2 text-[13px] leading-5 text-ink-2">{{ c.description }}</p>
            </div>
          </div>
        </li>
      </ul>

      <div class="mt-4 flex justify-end">
        <button class="btn-primary w-full sm:w-auto" :disabled="!selected.size || importing" @click="doImport">
          <Icon name="plus" :size="15" class="i-plus" />{{ importing ? '加入中…' : `加入 ${selected.size} 个` }}
        </button>
      </div>
    </div>
  </div>
</template>
