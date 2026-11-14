<script setup>
import { computed, onMounted, ref } from 'vue'
import { api, formatStars, isCancelled } from '../../api'
import Icon from '../../components/Icon.vue'
import { toast } from '../../composables/toast'
import ASelect from '../components/ASelect.vue'

// 采集待确认：每日采集里 AI 拿不准的仓库，由管理员决定收录（可指定分类）或忽略（以后不再判定）
const emit = defineEmits(['changed'])
const items = ref(null)
const tree = ref([])
const picked = ref({}) // 条目 id → 指定的子类 id（'' 表示交给 AI）
const busy = ref(new Set())

const catOptions = computed(() => [
  { value: '', label: '交给 AI 判定' },
  ...tree.value.flatMap((g) => g.children.map((c) => ({ value: c.id, label: c.name, group: g.name }))),
])

async function load() {
  try {
    items.value = await api('/api/review')
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  }
}

async function act(it, action) {
  busy.value = new Set(busy.value).add(it.id)
  try {
    const body = action === 'approve' && picked.value[it.id] ? { category_id: picked.value[it.id] } : undefined
    await api(`/api/review/${it.id}/${action}`, { method: 'POST', admin: true, body })
    items.value = items.value.filter((x) => x.id !== it.id)
    toast(action === 'approve' ? `已收录「${it.name}」，正在提炼` : `已忽略「${it.name}」，以后不再判定`, 'success')
    emit('changed')
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  } finally {
    const s = new Set(busy.value)
    s.delete(it.id)
    busy.value = s
  }
}

onMounted(async () => {
  load()
  try {
    tree.value = await api('/api/categories')
  } catch {}
})
</script>

<template>
  <div>
    <h1 class="m-0 text-xl font-semibold">采集待确认</h1>
    <p class="mt-1 mb-5 text-[13px] text-mute">每日自动采集时，AI 拿不准是否该收录的仓库会停在这里。收录后才会出现在列表并参与榜单；忽略的仓库以后不再判定。</p>

    <section class="card">
      <div class="card-hd"><h2>待确认</h2><span v-if="items?.length" class="tag tag-warn">{{ items.length }}</span></div>
      <div v-if="!items" class="card-bd"><div class="skeleton h-40" /></div>
      <p v-else-if="!items.length" class="empty">没有待确认的仓库</p>
      <ul v-else class="m-0 list-none p-0">
        <li v-for="it in items" :key="it.id" class="border-b border-line px-[18px] py-4 last:border-0">
          <div class="flex flex-wrap items-center gap-x-3 gap-y-1">
            <a :href="it.github_url" target="_blank" rel="noopener" class="inline-flex items-center gap-1 font-semibold hover:text-primary">{{ it.repo_full_name }}<Icon name="external-link" :size="13" /></a>
            <span class="flex items-center gap-1 text-[13px] text-ink-2 tabular-nums"><Icon name="star" :size="13" />{{ formatStars(it.stars) }}</span>
            <span v-if="it.language" class="text-[13px] text-mute">{{ it.language }}</span>
          </div>
          <p class="mt-1.5 mb-0 text-[13.5px] text-ink-2">{{ it.summary || '无简介' }}</p>
          <p class="mt-2 mb-0 rounded-md bg-warn-soft px-3 py-1.5 text-[12.5px] text-warn"><span v-if="it.review_note.startsWith('AI')" class="tag tag-blue mr-1.5 h-5">AI</span>{{ it.review_note }}</p>
          <div v-if="it.topics.length" class="mt-2 flex flex-wrap gap-1.5">
            <span v-for="t in it.topics.slice(0, 8)" :key="t" class="tag tag-gray">{{ t }}</span>
          </div>
          <div class="mt-3 flex flex-wrap items-center gap-2">
            <ASelect v-model="picked[it.id]" :options="catOptions" :label="`${it.name} 的分类`" searchable class="w-full sm:w-60" />
            <span class="ml-auto flex gap-2">
              <button class="btn btn-danger" :disabled="busy.has(it.id)" @click="act(it, 'reject')"><Icon name="x" :size="15" />忽略</button>
              <button class="btn btn-primary" :disabled="busy.has(it.id)" @click="act(it, 'approve')"><Icon name="check" :size="15" />收录</button>
            </span>
          </div>
        </li>
      </ul>
    </section>
  </div>
</template>
