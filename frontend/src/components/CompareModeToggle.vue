<script setup>
import { compareState, setCompareMode } from '../composables/compare'
import Icon from './Icon.vue'

// 「AI 智能对比」开关：打开后卡片和 GitHub 搜索结果上出现对比勾选框，底部出现对比栏
</script>

<template>
  <button
    type="button"
    role="switch"
    :aria-checked="compareState.mode"
    class="rp flex h-8 shrink-0 cursor-pointer items-center gap-2 rounded-[7px] border px-2.5 text-[12.5px] max-[420px]:gap-1.5 max-[420px]:px-2 transition-[color,background-color,border-color,box-shadow] duration-300"
    :class="compareState.mode ? 'border-brand bg-brand font-medium text-white shadow-[0_6px_14px_-8px_rgb(30_86_214/0.9)]' : 'border-line bg-panel text-ink-2 hover:border-brand hover:text-brand'"
    :title="compareState.mode ? '关闭 AI 智能对比' : '打开后勾选 2~6 个条目，AI 帮你多维度对比'"
    @click="setCompareMode(!compareState.mode)"
  >
    <Icon name="layers" :size="15" class="max-[420px]:hidden" />AI 智能对比
    <span class="relative h-[18px] w-8 rounded-full transition-colors" :class="compareState.mode ? 'bg-white/35' : 'bg-ink/15'">
      <span class="absolute top-[2px] h-[14px] w-[14px] rounded-full bg-white shadow transition-[left] duration-300" :class="compareState.mode ? 'left-[16px]' : 'left-[2px]'" />
    </span>
  </button>
</template>
