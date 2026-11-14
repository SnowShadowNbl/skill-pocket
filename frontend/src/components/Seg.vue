<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import Icon from './Icon.vue'

// 滑块分段控件：选中底块跟着滑过去（弹簧缓动）。
// variant：brand 蓝底白字（主筛选）/ soft 浅底白块蓝字（范围切换）/ mini 小号（卡片头部的日榜周榜）
const props = defineProps({
  modelValue: { type: [String, Number, Boolean], default: '' },
  options: { type: Array, required: true }, // [[value, label, icon?, extra?]]
  variant: { type: String, default: 'brand' },
  label: { type: String, default: '' },
  hideLabelOnMobile: Boolean,
})
const emit = defineEmits(['update:modelValue'])
const box = ref(null)
const thumb = ref({ opacity: 0 })

function measure() {
  const b = box.value?.querySelector('[aria-pressed="true"]')
  thumb.value = b ? { width: `${b.offsetWidth}px`, transform: `translateX(${b.offsetLeft}px)`, opacity: 1 } : { opacity: 0 }
}
watch(() => [props.modelValue, props.options.length], () => nextTick(measure))
let ro
onMounted(() => {
  measure()
  document.fonts?.ready.then(measure)
  ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(measure) : null
  ro?.observe(box.value)
})
onBeforeUnmount(() => ro?.disconnect())
defineExpose({ measure })

const V = {
  brand: { box: 'border border-line bg-panel p-[2px] rounded-[7px]', thumb: 'bg-brand shadow-[0_6px_14px_-8px_rgb(30_86_214/0.9)]', btn: 'px-3 py-[5px] text-[12.5px]', on: 'text-white', off: 'text-ink-2 hover:text-brand' },
  soft: { box: 'bg-hover p-[3px] rounded-[7px]', thumb: 'bg-white shadow-[0_1px_3px_rgb(11_47_122/0.14)]', btn: 'px-2.5 py-1.5 text-[12.5px]', on: 'font-medium text-brand', off: 'text-ink-2 hover:text-ink' },
  // v3.3.10 下划线标签（手机首页搜索框上方的「站内 / GitHub」，与小程序一致）
  line: { box: 'seg-line gap-5 pb-[1px]', thumb: 'bg-brand', btn: 'px-0.5 pt-1 pb-2 text-[14.5px]', on: 'font-semibold text-ink', off: 'text-mute hover:text-ink-2' },
  mini: { box: 'bg-hover p-[2px] rounded-[6px]', thumb: 'bg-white shadow-[0_1px_2px_rgb(11_47_122/0.14)] !rounded-[4px]', btn: 'px-2 py-[3px] text-[11px]', on: 'font-medium text-brand', off: 'text-mute hover:text-ink-2' },
}
</script>

<template>
  <div ref="box" class="relative flex shrink-0" :class="V[variant].box" role="group" :aria-label="label">
    <span class="seg-thumb" :class="V[variant].thumb" :style="thumb" />
    <button
      v-for="o in options"
      :key="String(o[0])"
      type="button"
      class="rp relative z-[1] flex cursor-pointer items-center gap-1.5 rounded-[5px] leading-[18px] whitespace-nowrap transition-colors duration-300"
      :class="[V[variant].btn, modelValue === o[0] ? V[variant].on : V[variant].off]"
      :aria-pressed="modelValue === o[0]"
      @click="emit('update:modelValue', o[0])"
    >
      <Icon v-if="o[2]" :name="o[2]" :size="13" />
      <span :class="{ 'max-[479px]:hidden': hideLabelOnMobile && o[2] }">{{ o[1] }}</span>
      <slot name="extra" :option="o" />
    </button>
  </div>
</template>
