<script setup>
import { homeMode, setHomeMode } from '../composables/homeMode'

// v3.3.96 首页模式开关（顶栏铃铛旁，与小程序一致）：小号胶囊分段，蓝色滑块滑过去
function pick(m) {
  if (homeMode.value !== m) setHomeMode(m)
}
</script>

<template>
  <div class="ms relative flex h-8 shrink-0 items-center rounded-full p-[3px]" role="radiogroup" aria-label="首页模式">
    <span class="ms-thumb absolute top-[3px] bottom-[3px] left-[3px] w-[44px] rounded-full" :style="{ transform: `translateX(${homeMode.value === 'simple' ? 44 : 0}px)` }" />
    <button v-for="m in [['classic', '经典'], ['simple', '简洁']]" :key="m[0]" type="button" role="radio" :aria-checked="homeMode.value === m[0]"
      class="ms-opt relative grid h-full w-[44px] cursor-pointer place-items-center text-[12px]" :class="{ 'is-on': homeMode.value === m[0] }" @click="pick(m[0])">{{ m[1] }}</button>
  </div>
</template>

<style scoped>
.ms { background: var(--color-hover); }
.ms-thumb { background: linear-gradient(135deg, #2f6bf0, #1e56d6); box-shadow: 0 4px 10px -4px rgb(30 86 214 / 0.7); transition: transform 0.45s var(--ease-spring); }
.ms-opt { color: var(--color-ink-2); transition: color 0.3s; }
.ms-opt:hover { color: var(--color-brand); }
.ms-opt.is-on { color: #fff; font-weight: 600; }
</style>
