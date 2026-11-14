<script setup>
import { computed, onMounted, ref } from 'vue'
import { api, formatTime } from '../api'
import { openFeedback } from '../composables/feedback'
import Icon from './Icon.vue'

const data = ref(null)
const STATUS_CLS = {
  new: 'bg-slate-100 text-slate-600',
  processing: 'bg-sky-50 text-sky-600',
  resolved: 'bg-ok-soft text-ok',
  wontfix: 'bg-slate-200 text-slate-600',
}

// v3.3 处理进度公开：待处理 → 处理中 → 已解决（不处理的也走到最后一步，标成「不处理」）
const STEPS = ['待处理', '处理中', '已解决']
const stepOf = (st) => ({ new: 0, processing: 1, resolved: 2, wontfix: 2 })[st] ?? 0
const counts = computed(() => {
  const c = { new: 0, processing: 0, done: 0 }
  for (const f of data.value?.items || []) c[f.status === 'new' ? 'new' : f.status === 'processing' ? 'processing' : 'done']++
  return c
})

onMounted(async () => {
  data.value = await api('/api/me/feedback').catch(() => ({ items: [], unread: 0 }))
  if (data.value.unread) api('/api/me/feedback/read', { method: 'POST' }).catch(() => {})
})
</script>

<template>
  <div>
    <div class="mb-3 flex items-center gap-2">
      <p v-if="data?.items.length" class="flex flex-wrap gap-x-3 text-[13px] text-ink-2">
        <span>待处理 <b class="text-ink tabular-nums">{{ counts.new }}</b></span>
        <span>处理中 <b class="text-sky-600 tabular-nums">{{ counts.processing }}</b></span>
        <span>已完成 <b class="text-ok tabular-nums">{{ counts.done }}</b></span>
      </p>
      <p v-else class="text-sm text-ink-2">你提交的反馈和处理进度</p>
      <button class="btn-primary btn-sm ml-auto" @click="openFeedback()"><Icon name="plus" :size="15" />新反馈</button>
    </div>
    <div v-if="!data" class="space-y-2"><div v-for="n in 3" :key="n" class="skeleton-bar h-20 rounded-2xl" /></div>
    <div v-else-if="!data.items.length" class="panel px-6 py-12 text-center text-sm text-ink-2">还没有提交过反馈</div>
    <ul v-else class="space-y-2">
      <li v-for="f in data.items" :key="f.id" class="panel p-4" :class="{ 'ring-2 ring-brand/40': f.user_unread }">
        <div class="flex flex-wrap items-center gap-2 text-xs">
          <span class="tag bg-brand-soft text-brand">{{ f.category_label }}</span>
          <span class="tag" :class="STATUS_CLS[f.status]">{{ f.status === 'new' ? '待处理' : f.status_label }}</span>
          <span v-if="f.user_unread" class="tag bg-brand-2 text-white">新回复</span>
          <span v-if="f.input_type === 'voice'" class="tag bg-white/70 text-ink-2"><Icon name="mic" :size="12" />语音</span>
          <time class="ml-auto text-mute">{{ formatTime(f.created_at) }}</time>
        </div>
        <p class="mt-2 text-[14.5px] leading-relaxed break-words whitespace-pre-wrap">{{ f.content }}</p>
        <!-- 处理进度 -->
        <div class="fb-steps mt-3 flex items-center" :aria-label="`处理进度：${f.status_label}`">
          <template v-for="(st, k) in STEPS" :key="st">
            <span class="flex items-center gap-1.5 text-[12px] whitespace-nowrap" :class="k <= stepOf(f.status) ? (f.status === 'wontfix' && k === 2 ? 'text-mute' : 'font-medium text-brand') : 'text-mute'">
              <span class="grid h-[18px] w-[18px] place-items-center rounded-full text-[10px] font-bold transition-colors duration-500" :class="k < stepOf(f.status) || (k === 2 && f.status === 'resolved') ? 'bg-brand text-white' : k === stepOf(f.status) ? 'bg-brand-soft text-brand ring-2 ring-brand/30' : 'bg-line-2 text-mute'">
                <Icon v-if="k < stepOf(f.status) || (k === 2 && f.status === 'resolved')" name="check" :size="11" />
                <template v-else>{{ k + 1 }}</template>
              </span>
              {{ k === 2 && f.status === 'wontfix' ? '不处理' : st }}
            </span>
            <span v-if="k < 2" class="mx-2 h-[2px] min-w-4 flex-1 overflow-hidden rounded-full bg-line-2"><i class="fb-fill block h-full bg-brand" :style="{ width: k < stepOf(f.status) ? '100%' : '0%' }" /></span>
          </template>
        </div>
        <div v-if="f.images.length" class="mt-2 flex gap-2">
          <a v-for="src in f.images" :key="src" :href="src" target="_blank" class="h-16 w-16 overflow-hidden rounded-lg border border-edge"><img :src="src" alt="截图" class="h-full w-full object-cover" /></a>
        </div>
        <ol v-if="f.replies?.length" class="mt-3 space-y-2 border-l-2 border-brand/25 pl-3">
          <li v-for="(r, i) in f.replies" :key="i" class="rounded-lg bg-brand-soft px-3 py-2.5 text-[13.5px] leading-relaxed">
            <p class="mb-0.5 text-xs font-semibold text-brand">管理员回复<template v-if="r.at"> · {{ formatTime(r.at) }}</template></p>
            <p v-if="r.text" class="break-words whitespace-pre-wrap">{{ r.text }}</p>
            <div v-if="r.images?.length" class="mt-2 flex flex-wrap gap-2">
              <a v-for="src in r.images" :key="src" :href="src" target="_blank" class="h-20 w-20 overflow-hidden rounded-md border border-line"><img :src="src" alt="回复截图" class="h-full w-full object-cover" /></a>
            </div>
          </li>
        </ol>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.fb-fill {
  transition: width 0.8s var(--ease-out-expo);
}
</style>
