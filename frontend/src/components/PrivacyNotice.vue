<script setup>
import { onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'

// 首次访问时告知会记录访问数据（只提示一次）
const KEY = 'skp_privacy_ok'
const show = ref(false)

onMounted(() => {
  try {
    show.value = !localStorage.getItem(KEY)
  } catch {
    show.value = false
  }
})

function ok() {
  show.value = false
  try {
    localStorage.setItem(KEY, '1')
  } catch {}
}
</script>

<template>
  <Transition name="list-fade">
    <div
      v-if="show"
      class="glass fixed inset-x-3 bottom-[calc(env(safe-area-inset-bottom)+76px)] z-[60] flex items-center gap-3 rounded-2xl px-4 py-3 text-[13px] text-ink-2 shadow-lg sm:inset-x-auto sm:right-5 sm:bottom-5 sm:w-[26rem]"
      role="status"
    >
      <p class="min-w-0 flex-1">
        为了防刷和改进服务，本站会记录访问的页面、操作、设备和 IP 所在地区（省市级）。详见
        <RouterLink to="/privacy" class="font-medium text-brand hover:underline">隐私政策</RouterLink>。
      </p>
      <button class="btn-primary btn-sm shrink-0" @click="ok">知道了</button>
    </div>
  </Transition>
</template>
