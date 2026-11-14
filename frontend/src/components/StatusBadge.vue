<script setup>
import { computed } from 'vue'
import { timeAgo } from '../api'
import Icon from './Icon.vue'

// 提交条目的状态标识：排队 / AI 提炼 / AI 审核 / 待管理员审核 / 已上线 / 未通过 / 处理失败 / 已下线
// 每个状态说明是「系统自动」还是「管理员」做的更新，以及更新时间
const props = defineProps({ item: { type: Object, required: true } })

const S = {
  queued: { label: '排队中', icon: 'clock', cls: 'bg-slate-100 text-slate-600', by: '系统自动' },
  extracting: { label: 'AI 提炼中', icon: 'sparkles', cls: 'bg-blue-50 text-blue-600', by: '系统自动', live: true },
  reviewing: { label: 'AI 审核中', icon: 'shield', cls: 'bg-sky-50 text-sky-600', by: '系统自动', live: true },
  admin: { label: '待管理员审核', icon: 'user', cls: 'bg-warn-soft text-warn', by: 'AI 已转交' },
  published: { label: '已上线', icon: 'check', cls: 'bg-ok-soft text-ok' },
  declined: { label: '未通过', icon: 'x', cls: 'bg-danger-soft text-danger' },
  failed: { label: '处理失败', icon: 'alert', cls: 'bg-danger-soft text-danger', by: '系统自动' },
  offline: { label: '已下线', icon: 'alert', cls: 'bg-slate-200 text-slate-600', by: '每日巡检' },
  hidden: { label: '已隐藏', icon: 'eye', cls: 'bg-slate-200 text-slate-600', by: '管理员' },
}

const state = computed(() => {
  const it = props.item
  if (it.status === 'offline') return 'offline'
  if (it.status === 'hidden') return 'hidden'
  if (it.status === 'declined') return 'declined'
  if (it.status === 'published') return 'published'
  if (it.ai_status === 'failed' && it.status !== 'awaiting') return 'failed'
  if (it.status === 'awaiting') {
    if (it.review_state === 'admin') return 'admin'
    if (it.ai_status === 'pending') return 'queued'
    if (it.ai_status === 'running') return 'extracting'
    return 'reviewing'
  }
  return 'published'
})
const s = computed(() => S[state.value])
const who = computed(() => {
  const r = props.item.last_review
  if (state.value === 'published' || state.value === 'declined') return r ? (r.reviewer === 'ai' ? 'AI 自动审核' : '管理员审核') : '系统自动'
  return s.value.by
})
const reason = computed(() => {
  if (state.value === 'declined') return props.item.review_note || props.item.last_review?.reason
  if (state.value === 'failed') return props.item.ai_error
  if (state.value === 'offline') return props.item.offline_reason
  if (state.value === 'admin') return props.item.last_review?.reason
  return ''
})
</script>

<template>
  <div class="flex flex-col gap-1">
    <div class="flex flex-wrap items-center gap-1.5 text-[11.5px]">
      <span class="inline-flex h-6 items-center gap-1 rounded-full px-2 font-semibold" :class="s.cls" role="status">
        <Icon :name="s.icon" :size="12" :class="{ 'animate-pulse': s.live }" />{{ s.label }}
      </span>
      <span v-if="who" class="text-mute">{{ who }}</span>
      <span class="text-mute">· {{ timeAgo(item.last_review?.at || item.updated_at || item.collected_at) }}</span>
    </div>
    <p v-if="reason" class="line-clamp-2 text-[12px] leading-relaxed" :class="state === 'declined' || state === 'failed' ? 'text-danger' : 'text-mute'">{{ reason }}</p>
  </div>
</template>
