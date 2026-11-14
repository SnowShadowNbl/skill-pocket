<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'
import CoverImage from './CoverImage.vue'
import Icon from './Icon.vue'

// 详情页图片集：多张图做成可滑动的轮播（手机手指左右滑，电脑点箭头或按 ← →），点图片全屏查看；只有一张或没有时和原来的封面一样
const props = defineProps({
  images: { type: Array, default: () => [] },
  name: String,
  category: Object,
})
const track = ref(null)
const index = ref(0)
const full = ref(false)

function go(i) {
  const n = props.images.length
  if (!n || !track.value) return
  index.value = (i + n) % n
  track.value.scrollTo({ left: index.value * track.value.clientWidth, behavior: 'smooth' })
}
function onScroll() {
  const el = track.value
  if (el) index.value = Math.round(el.scrollLeft / Math.max(1, el.clientWidth))
}
function onKey(e) {
  if (e.key === 'ArrowLeft') go(index.value - 1)
  else if (e.key === 'ArrowRight') go(index.value + 1)
  else if (e.key === 'Escape' && full.value) full.value = false
  else return
  e.preventDefault()
}
watch(() => props.images, () => {
  index.value = 0
  track.value?.scrollTo({ left: 0 })
})
watch(full, (v) => (v ? addEventListener('keydown', onKey) : removeEventListener('keydown', onKey)))
onBeforeUnmount(() => removeEventListener('keydown', onKey))
</script>

<template>
  <CoverImage v-if="images.length <= 1" :src="images[0]" :name="name" :category="category" class="aspect-[16/9] rounded-2xl border border-edge" />
  <div v-else class="group relative" role="region" aria-roledescription="轮播" :aria-label="`${name} 的图片，共 ${images.length} 张`" tabindex="0" @keydown="onKey">
    <div
      ref="track"
      class="scrollbar-none flex aspect-[16/9] snap-x snap-mandatory overflow-x-auto overscroll-x-contain rounded-2xl border border-edge bg-white/60"
      @scroll.passive="onScroll"
    >
      <button v-for="(src, i) in images" :key="src" type="button" class="h-full w-full shrink-0 cursor-zoom-in snap-center snap-always" :aria-label="`查看第 ${i + 1} 张大图`" @click="full = true">
        <img :src="src" :alt="`${name} 图 ${i + 1}`" class="h-full w-full object-contain" :loading="i === 0 ? 'eager' : 'lazy'" draggable="false" />
      </button>
    </div>
    <button class="carousel-arrow left-2" aria-label="上一张" @click="go(index - 1)"><Icon name="chevron-left" :size="18" /></button>
    <button class="carousel-arrow right-2" aria-label="下一张" @click="go(index + 1)"><Icon name="chevron-right" :size="18" /></button>
    <span class="absolute top-2 right-2 rounded-full bg-ink/60 px-2 py-0.5 text-[11.5px] text-white tabular-nums">{{ index + 1 }} / {{ images.length }}</span>
    <div class="absolute inset-x-0 bottom-2 flex justify-center gap-1.5">
      <button
        v-for="(_, i) in images"
        :key="i"
        class="h-1.5 cursor-pointer rounded-full transition-all duration-300"
        :class="i === index ? 'w-5 bg-white shadow' : 'w-1.5 bg-white/60 hover:bg-white/90'"
        :aria-label="`第 ${i + 1} 张`"
        :aria-current="i === index"
        @click="go(i)"
      />
    </div>

    <!-- 全屏查看 -->
    <Teleport to="body">
      <Transition name="list-fade">
        <div v-if="full" class="fixed inset-0 z-[90] flex flex-col bg-ink/90" role="dialog" aria-modal="true" :aria-label="`${name} 图片`" @click.self="full = false">
          <div class="flex items-center px-4 py-3 text-sm text-white/80">
            <span class="tabular-nums">{{ index + 1 }} / {{ images.length }}</span>
            <a :href="images[index]" target="_blank" class="ml-auto mr-2 rounded-lg px-2.5 py-1 hover:bg-white/10">原图</a>
            <button class="grid h-9 w-9 cursor-pointer place-items-center rounded-full hover:bg-white/10" aria-label="关闭" @click="full = false"><Icon name="x" :size="20" /></button>
          </div>
          <div class="relative flex min-h-0 flex-1 items-center justify-center px-4 pb-6" @click.self="full = false">
            <img :src="images[index]" :alt="`${name} 图 ${index + 1}`" class="max-h-full max-w-full rounded-lg object-contain" />
            <button class="carousel-arrow left-3 !opacity-100" aria-label="上一张" @click="go(index - 1)"><Icon name="chevron-left" :size="20" /></button>
            <button class="carousel-arrow right-3 !opacity-100" aria-label="下一张" @click="go(index + 1)"><Icon name="chevron-right" :size="20" /></button>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<style scoped>
.carousel-arrow {
  position: absolute;
  top: 50%;
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  border-radius: 999px;
  background: rgb(255 255 255 / 0.85);
  color: #1e293b;
  box-shadow: 0 4px 14px -6px rgb(15 23 42 / 0.4);
  transform: translateY(-50%);
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.2s;
}
.group:hover .carousel-arrow,
.group:focus-within .carousel-arrow {
  opacity: 1;
}
@media (hover: none) {
  .carousel-arrow {
    display: none;
  }
}
</style>
