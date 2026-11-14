<script setup>
import { computed } from 'vue'
import { inCompare, toggleCompare } from '../composables/compare'
import Icon from './Icon.vue'

// 「对比」勾选框：放在卡片上，点了不会打开详情
const props = defineProps({
  entry: { type: Object, required: true },
  small: Boolean, // 手机三列卡片上只显示图标
})
const on = computed(() => inCompare(props.entry))
</script>

<template>
  <button
    type="button"
    role="checkbox"
    :aria-checked="on"
    :aria-label="on ? `从对比中移除 ${entry.name}` : `把 ${entry.name} 加入对比`"
    class="flex cursor-pointer items-center gap-1 rounded-full font-medium backdrop-blur transition-all duration-200"
    :class="[
      small ? 'h-6 w-6 justify-center' : 'h-7 pr-2.5 pl-1.5 text-[12px]',
      on ? 'bg-brand text-white shadow-[0_4px_12px_-4px_rgb(30_86_214/0.7)]' : 'bg-white/85 text-ink-2 hover:bg-white hover:text-brand',
    ]"
    @click.prevent.stop="toggleCompare(entry)"
  >
    <span class="grid place-items-center rounded-[5px] border-[1.5px]" :class="[small ? 'h-3.5 w-3.5' : 'h-4 w-4', on ? 'border-white' : 'border-current']">
      <Icon v-if="on" name="check" :size="small ? 10 : 11" />
    </span>
    <span v-if="!small">对比</span>
  </button>
</template>
