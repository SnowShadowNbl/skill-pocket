<script setup>
import { computed, ref, watch } from 'vue'
import { api } from '../api'
import { useFinderJob } from '../composables/finder'
import { toast } from '../composables/toast'
import AiTag from './AiTag.vue'
import CandidateList from './CandidateList.vue'
import CompareModeToggle from './CompareModeToggle.vue'
import Icon from './Icon.vue'

// 功能搜索：说出想要的功能或项目名 → AI 生成英文关键词搜 GitHub → 按相关度排序 → 勾选加入。
// v3.0 由首页搜索框（GitHub 标签）驱动；AI 判断输入其实是一串项目时，后端转成逐个识别，这里通知外层切换视图
const emit = defineEmits(['manual', 'reroute'])
const q = ref('')
const { job, error, starting, start, poll, reset, adopt } = useFinderJob()
const asking = ref(false)

const STEPS = [
  ['plan', 'AI 理解需求'],
  ['search', '搜索 GitHub'],
  ['rank', 'AI 按相关度排序'],
]
const running = computed(() => job.value?.status === 'running')
const stepIndex = computed(() => STEPS.findIndex((s) => s[0] === job.value?.stage))
const queries = computed(() => (job.value?.plans || []).flatMap((p) => p.queries))

function go(text) {
  if (text) q.value = text
  if (!q.value.trim()) return
  start('/api/finder/search', { q: q.value.trim().slice(0, 300) })
}
watch(() => job.value?.rerouted, (v) => v && emit('reroute', job.value.id))
defineExpose({ go, reset, running })

async function more() {
  asking.value = true
  try {
    job.value = await api(`/api/finder/${job.value.id}/more`, { method: 'POST' })
    poll()
  } catch (e) {
    toast(e.message, 'error')
  } finally {
    asking.value = false
  }
}
</script>

<template>
  <div>
    <p v-if="error" class="mt-4 flex items-center gap-2 rounded-2xl bg-danger-soft p-3 text-sm text-danger" role="alert"><Icon name="alert" :size="16" />{{ error }}</p>

    <div v-if="job">
      <!-- 理解与关键词 -->
      <div v-if="job.plan?.understanding || queries.length" class="rounded-2xl border border-brand/15 bg-brand-soft/40 px-3.5 py-3">
        <p v-if="job.plan?.understanding" class="flex items-start gap-1.5 text-[13.5px]">
          <Icon name="sparkles" :size="15" class="mt-0.5 shrink-0 text-brand" /><span>{{ job.plan.understanding }}</span>
          <AiTag class="ml-auto shrink-0" />
        </p>
        <div v-if="queries.length" class="mt-2 flex flex-wrap gap-1.5">
          <code v-for="x in queries" :key="x" class="rounded-lg bg-white/80 px-2 py-0.5 font-mono text-[12px] text-ink-2">{{ x }}</code>
        </div>
      </div>

      <!-- 进度 -->
      <div v-if="running" class="mt-4" aria-live="polite">
        <ol class="flex items-center gap-2 text-[12.5px]">
          <li v-for="(s, k) in STEPS" :key="s[0]" class="flex items-center gap-1.5" :class="k < stepIndex ? 'text-ok' : k === stepIndex ? 'font-semibold text-brand' : 'text-mute'">
            <Icon :name="k < stepIndex ? 'check' : k === stepIndex ? 'refresh' : 'clock'" :size="13" :class="{ 'animate-spin': k === stepIndex }" />{{ s[1] }}
            <Icon v-if="k < STEPS.length - 1" name="chevron-right" :size="13" class="text-mute" />
          </li>
        </ol>
        <p class="mt-2 text-[13px] text-ink-2">{{ job.message }}</p>
        <CandidateList v-if="job.preliminary && job.candidates?.length" class="mt-3" :job-id="job.id" :candidates="job.candidates" mode="search" :auto-select="false" preview />
        <div v-else class="mt-3 space-y-2"><div v-for="n in 4" :key="n" class="skeleton-bar h-[74px] rounded-2xl" /></div>
      </div>

      <template v-else>
        <p v-if="job.status === 'failed'" class="flex items-center gap-2 rounded-2xl bg-danger-soft p-3 text-sm text-danger" role="alert"><Icon name="alert" :size="16" />{{ job.error || job.message }}</p>
        <p v-else-if="job.warning" class="mt-3 text-xs text-warn">{{ job.warning }}</p>
        <div v-if="job.status !== 'failed'" class="mt-4 mb-2 flex flex-wrap items-center gap-2">
          <p class="m-0 flex min-w-0 flex-1 items-center gap-2 text-[15px] font-semibold">{{ job.message }}<AiTag v-if="job.candidates?.some((c) => c.reason)" /></p>
          <!-- AI 智能对比：打开后结果卡片上出现对比勾选，可以和站内条目一起对比 -->
          <CompareModeToggle v-if="job.candidates?.length" />
        </div>
        <CandidateList v-if="job.candidates?.length" :job-id="job.id" :candidates="job.candidates" mode="search" @manual="(v) => emit('manual', v)" @adopt="adopt" />
        <div v-if="job.status !== 'failed'" class="mt-3 flex flex-wrap gap-2">
          <button class="btn-glass btn-sm" :disabled="asking" @click="more"><Icon name="refresh" :size="15" />换个说法再搜</button>
        </div>
      </template>
    </div>

  </div>
</template>
