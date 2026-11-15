<script setup>
import { computed } from 'vue'
import { hideBindBar, showBindBar } from '../composables/bindTip'
import { meta } from '../composables/meta'
import { openBindWechat } from '../composables/quota'
import Icon from './Icon.vue'

// v3.3.100 首页搜索框下方的细提示条：只有邮箱、还没领过免费额度的账号显示；绑定后或关掉后不再出现
const free = computed(() => {
  const n = meta.data?.free_quota || 0
  return n >= 10000 && n % 10000 === 0 ? `${n / 10000} 万` : n.toLocaleString()
})
</script>

<template>
  <Transition name="toast">
    <div v-if="showBindBar()" class="bind-bar flex items-center gap-2 rounded-[10px] py-1.5 pr-1.5 pl-3 text-[13px]" role="note">
      <Icon name="message" :size="15" class="shrink-0 text-brand" />
      <span class="min-w-0 flex-1 truncate text-ink-2">绑定微信领取 <b class="font-semibold text-brand">{{ free }}额度</b></span>
      <button type="button" class="btn-primary btn-sm shrink-0" @click="openBindWechat('tip')">去绑定</button>
      <button type="button" class="grid h-8 w-8 shrink-0 cursor-pointer place-items-center rounded-md text-mute hover:bg-white/70 hover:text-ink" aria-label="不再提示" @click="hideBindBar"><Icon name="x" :size="14" /></button>
    </div>
  </Transition>
</template>

<style scoped>
.bind-bar { background: var(--color-brand-soft); box-shadow: inset 0 0 0 1px rgb(30 86 214 / 0.16); }
</style>
