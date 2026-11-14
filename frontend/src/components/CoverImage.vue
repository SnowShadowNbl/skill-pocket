<script setup>
import { computed, ref } from 'vue'
import Icon from './Icon.vue'
import { groupStyle } from '../categoryStyle'

const props = defineProps({
  src: String,
  name: String,
  category: Object, // { code, name, group_code }
  size: { type: Number, default: 30 }, // 无图时图标大小
  float: Boolean, // 无图时图标轻微漂浮
  delay: { type: Number, default: 0 },
})

const failed = ref(false)
// 方形 / 竖图多半是 logo，裁成横图会只剩空白，改为完整显示
const contain = ref(false)
const style = computed(() => groupStyle(props.category?.group_code))

function onLoad(e) {
  const { naturalWidth: w, naturalHeight: h } = e.target
  contain.value = w / h < 1.3
}
</script>

<template>
  <div class="group/cover relative grid place-items-center overflow-hidden">
    <img
      v-if="src && !failed"
      :src="src"
      :alt="`${name} 封面`"
      loading="lazy"
      class="h-full w-full transition-transform duration-700 ease-out-expo group-hover:scale-105"
      :class="contain ? 'bg-white object-contain p-[12%]' : 'object-cover'"
      @load="onLoad"
      @error="failed = true"
    />
    <template v-else>
      <!-- 柔光色团 -->
      <span
        class="absolute h-28 w-28 rounded-full opacity-20 blur-2xl transition-[transform,opacity] duration-700 ease-out-expo group-hover:scale-140 group-hover:opacity-30"
        :style="{ background: style.fg }"
      />
      <span class="absolute inset-0 bg-[linear-gradient(rgb(30_86_214/0.07)_1px,transparent_1px),linear-gradient(90deg,rgb(30_86_214/0.07)_1px,transparent_1px)] bg-[size:20px_20px]" />
      <span
        class="relative grid place-items-center rounded-[10px] border border-line bg-white/85"
        :class="float ? 'float-y' : ''"
        :style="{ color: style.fg, width: size * 2 + 'px', height: size * 2 + 'px', animationDelay: `${delay * -0.6}s` }"
      >
        <Icon :name="style.icon" :size="size" />
      </span>
    </template>
  </div>
</template>
