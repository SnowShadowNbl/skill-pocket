<script setup>
import { useRoute } from 'vue-router'
import Icon from '../components/Icon.vue'

// v3.1：不存在的地址不再空白，给出回首页 / 去收录两个出口
const route = useRoute()
</script>

<template>
  <div class="flex min-h-[56vh] flex-col items-center justify-center px-6 py-16 text-center">
    <div v-reveal="0" class="relative">
      <span class="float-y grid h-16 w-16 place-items-center rounded-2xl bg-brand-soft text-brand shadow-[0_14px_30px_-18px_rgb(30_86_214/0.7)]">
        <Icon name="search" :size="28" />
      </span>
      <span class="absolute -top-2 -right-3 rounded-full bg-brand px-2 py-0.5 font-mono text-[11px] font-semibold text-white">404</span>
    </div>
    <h1 v-reveal="1" class="mt-6 text-xl font-semibold tracking-[-0.02em]">这个页面不存在</h1>
    <p v-reveal="2" class="mt-2 max-w-[340px] truncate font-mono text-[12.5px] text-mute">{{ route.fullPath }}</p>
    <div v-reveal="3" class="mt-6 flex flex-wrap justify-center gap-2">
      <RouterLink to="/" class="btn-primary"><Icon name="home" :size="15" />回首页</RouterLink>
      <RouterLink :to="{ path: '/', query: { scope: 'github' } }" class="btn-glass"><Icon name="github" :size="15" />去 GitHub 收录</RouterLink>
    </div>
  </div>
</template>
