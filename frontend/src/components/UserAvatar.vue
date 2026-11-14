<script setup>
import { computed } from 'vue'

// 头像：用户上传的图片（avatar 以 avatars/ 开头），或预设的渐变色底 + 昵称首字（key 与后端 account.AVATARS 一致）
const props = defineProps({
  user: { type: Object, default: null },
  size: { type: Number, default: 32 },
})

const GRADIENTS = {
  indigo: ['#1E56D6', '#2F6BF0'],
  pink: ['#5AA2FF', '#f472b6'],
  teal: ['#14b8a6', '#0ea5e9'],
  amber: ['#f59e0b', '#f97316'],
  violet: ['#2F6BF0', '#d946ef'],
  sky: ['#0ea5e9', '#1E56D6'],
  rose: ['#f43f5e', '#fb7185'],
  lime: ['#65a30d', '#14b8a6'],
}
const FALLBACK = ['#94a3b8', '#64748b']

const initial = computed(() => {
  const n = (props.user?.nickname || '?').trim()
  return Array.from(n)[0]?.toUpperCase() || '?'
})
const image = computed(() => (props.user?.avatar?.startsWith('avatars/') ? `/media/${props.user.avatar}` : ''))
const bg = computed(() => {
  const [a, b] = GRADIENTS[props.user?.avatar] || FALLBACK
  return `linear-gradient(135deg, ${a}, ${b})`
})
</script>

<template>
  <img
    v-if="image"
    :src="image"
    alt=""
    class="inline-block shrink-0 rounded-full bg-ink/5 object-cover"
    :style="{ width: `${size}px`, height: `${size}px` }"
    loading="lazy"
    aria-hidden="true"
  />
  <span
    v-else
    class="inline-grid shrink-0 place-items-center rounded-full font-semibold text-white select-none"
    :style="{ width: `${size}px`, height: `${size}px`, fontSize: `${Math.round(size * 0.44)}px`, background: bg }"
    aria-hidden="true"
  >{{ initial }}</span>
</template>

<script>
export const AVATAR_KEYS = ['indigo', 'pink', 'teal', 'amber', 'violet', 'sky', 'rose', 'lime']
</script>
