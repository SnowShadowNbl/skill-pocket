<script setup>
import { computed, ref } from 'vue'
import { isFav, toggleFav } from '../composables/favorites'
import FolderPicker from './FolderPicker.vue'
import Icon from './Icon.vue'
import { burst } from '../composables/motion'

const props = defineProps({
  item: { type: Object, required: true },
  variant: { type: String, default: 'icon' }, // icon：圆形按钮；mini：卡片底栏的小爱心；button：详情页的完整按钮
})
defineOptions({ inheritAttrs: false }) // 根节点有两个（按钮 + 浮层），class 等透传给按钮
const emit = defineEmits(['change'])

const on = computed(() => isFav(props.item))
const popping = ref(false)
const busy = ref(false)
const btn = ref(null)
const picker = ref(false)

async function toggle() {
  if (busy.value) return
  busy.value = true
  if (!on.value) {
    popping.value = false
    requestAnimationFrame(() => (popping.value = true))
    burst(btn.value)
    navigator.userActivation?.hasBeenActive && navigator.vibrate?.(10)
  }
  const result = await toggleFav(props.item)
  busy.value = false
  picker.value = result // 收藏成功后弹出「放进分类」
  emit('change', result)
}
</script>

<template>
  <button
    ref="btn"
    v-bind="$attrs"
    type="button"
    :aria-pressed="on"
    :aria-label="on ? `取消收藏 ${item.name}` : `收藏 ${item.name}`"
    :title="on ? '取消收藏' : '收藏'"
    :class="
      variant === 'mini'
        ? ['relative -my-1 -mr-1 grid h-6 w-6 shrink-0 cursor-pointer place-items-center rounded-full transition-[color,background-color,transform] duration-300 hover:bg-brand-soft hover:text-brand active:scale-80', on ? 'text-brand' : 'text-mute']
        : variant === 'icon'
        ? 'relative grid h-10 w-10 cursor-pointer place-items-center rounded-full border border-edge bg-white/75 backdrop-blur transition-[transform,background-color] duration-300 ease-out-expo hover:scale-110 hover:bg-white active:scale-90'
        : ['btn-glass', on ? 'text-brand' : '']
    "
    @click.stop.prevent="toggle"
  >
    <span class="relative grid place-items-center">
      <!-- 收藏时的扩散光圈 -->
      <span v-if="popping && on" class="fav-burst absolute inset-0 rounded-full" @animationend="popping = false" />
      <Icon
        name="heart"
        :size="variant === 'mini' ? 14 : variant === 'icon' ? 19 : 17"
        class="relative transition-colors duration-300"
        :class="[on ? 'fill-brand text-brand' : variant === 'mini' ? '' : 'text-ink-2', popping && on ? 'fav-pop' : '']"
      />
    </span>
    <template v-if="variant === 'button'">{{ on ? '已收藏' : '收藏' }}</template>
  </button>
  <FolderPicker :item="item" :anchor="btn" :open="picker && on" @close="picker = false" />
</template>

<style scoped>
.fav-pop {
  animation: fav-pop 0.5s cubic-bezier(0.34, 1.56, 0.64, 1);
}
@keyframes fav-pop {
  0% { transform: scale(0.6); }
  45% { transform: scale(1.35); }
  100% { transform: scale(1); }
}
.fav-burst {
  box-shadow: 0 0 0 0 rgb(30 86 214 / 0.55);
  animation: fav-burst 0.6s ease-out forwards;
}
@keyframes fav-burst {
  to { box-shadow: 0 0 0 14px rgb(30 86 214 / 0); }
}
@media (prefers-reduced-motion: reduce) {
  .fav-pop, .fav-burst { animation: none; }
}
</style>
