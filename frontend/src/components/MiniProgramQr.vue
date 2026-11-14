<script setup>
import { onBeforeUnmount, watch } from 'vue'
import Icon from './Icon.vue'

// v3.3.30 PC 顶栏「小程序」：弹出小程序码，微信扫一扫直接打开 Skill Pocket 小程序（正式版）
const open = defineModel({ type: Boolean, default: false })

function onKey(e) {
  if (e.key === 'Escape') open.value = false
}
watch(open, (v) => (v ? addEventListener('keydown', onKey) : removeEventListener('keydown', onKey)))
onBeforeUnmount(() => removeEventListener('keydown', onKey))
</script>

<template>
  <Teleport to="body">
    <Transition name="sheet">
      <div v-if="open" class="fixed inset-0 z-[75] grid place-items-center bg-ink/25 p-4 backdrop-blur-[6px]" @click.self="open = false">
        <div class="sheet-panel relative w-full max-w-[340px] rounded-2xl border border-line bg-white p-6 text-center shadow-[0_30px_70px_-30px_rgb(11_47_122/0.6)]" role="dialog" aria-label="Skill Pocket 小程序">
          <button class="absolute top-3 right-3 grid h-8 w-8 cursor-pointer place-items-center rounded-full text-mute transition-colors hover:bg-hover hover:text-ink" aria-label="关闭" @click="open = false">
            <Icon name="x" :size="16" />
          </button>
          <h2 class="text-[17px] font-bold tracking-tight">Skill Pocket 小程序</h2>
          <div class="mx-auto mt-4 grid h-[220px] w-[220px] place-items-center rounded-2xl border border-line bg-white p-2.5 shadow-[0_14px_30px_-20px_rgb(11_47_122/0.5)]">
            <img src="/mp-qrcode.jpg" alt="Skill Pocket 小程序码" class="h-full w-full object-contain" />
          </div>
          <p class="mt-4 flex items-center justify-center gap-1.5 text-[13.5px] text-ink-2">
            <Icon name="camera" :size="15" class="text-brand" />微信扫一扫，打开小程序
          </p>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>
