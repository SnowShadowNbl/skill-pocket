<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { goCollect } from '../composables/collect'
import { closeTour, tourState } from '../composables/onboarding'
import Icon from './Icon.vue'

// v3.3 新手引导：Skill Pocket 的三个核心能力，三步看完；可以跳过，看过一次就不再自动弹
const router = useRouter()
const STEPS = [
  {
    icon: 'github',
    tag: 'GitHub 中文中转站',
    title: '用中文搜 GitHub',
    body: '说一句你想要的功能，AI 帮你翻成关键词去 GitHub 找，再用中文讲清每个项目是干什么的。',
    chips: ['一句话找功能', '贴仓库链接', '截图识别'],
  },
  {
    icon: 'pocket',
    tag: '你的技能口袋',
    title: '随手收藏，AI 帮你整理',
    body: '看到好用的 Skill、模型、工具就放进口袋，AI 自动按领域和用途归好类，不会东一条西一条找不到。',
    chips: ['一键收藏', '自动分类', '收藏备注'],
  },
  {
    icon: 'sparkles',
    tag: 'AI 对比',
    title: '同类项目，AI 帮你选',
    body: '勾选几个同类的开源项目，AI 从功能、上手难度、部署方式等方面对比差异，直接给出建议。',
    chips: ['多维度对比', '给出建议', '对比记录存进口袋'],
  },
]
const step = computed(() => STEPS[tourState.step])
const last = computed(() => tourState.step === STEPS.length - 1)

function next() {
  if (last.value) finish()
  else tourState.step++
}
function finish() {
  closeTour()
}
function tryIt() {
  closeTour()
  goCollect(router)
}
</script>

<template>
  <Teleport to="body">
    <Transition name="sheet">
      <div v-if="tourState.open" class="fixed inset-0 z-[80] grid place-items-end bg-ink/30 backdrop-blur-[6px] sm:place-items-center" role="dialog" aria-modal="true" aria-label="新手引导" @click.self="finish" @keydown.esc="finish">
        <div class="sheet-panel glass-strong pb-safe relative w-full overflow-hidden rounded-t-[16px] shadow-[0_-24px_60px_-24px_rgb(11_47_122/0.45)] sm:max-w-[440px] sm:rounded-[16px]">
          <!-- 插画区：大图标 + 漂浮光斑，切步骤时换色 -->
          <div class="tour-hero relative grid h-[170px] place-items-center overflow-hidden" :data-step="tourState.step">
            <span class="tour-blob a" />
            <span class="tour-blob b" />
            <Transition name="tour-ic" mode="out-in">
              <span :key="tourState.step" class="tour-ic relative grid h-20 w-20 place-items-center rounded-[22px] bg-white text-brand shadow-[0_18px_36px_-16px_rgb(11_47_122/0.6)]">
                <Icon :name="step.icon" :size="38" />
              </span>
            </Transition>
            <button class="absolute top-3 right-3 cursor-pointer rounded-full bg-white/70 px-3 py-1 text-[12.5px] text-ink-2 backdrop-blur hover:bg-white" @click="finish">跳过</button>
          </div>

          <div class="px-6 pt-5 pb-6">
            <Transition name="tour-txt" mode="out-in">
              <div :key="tourState.step">
                <span class="tag bg-brand-soft text-brand">{{ tourState.step + 1 }} / 3 · {{ step.tag }}</span>
                <h2 class="mt-2.5 text-[20px] font-bold tracking-tight">{{ step.title }}</h2>
                <p class="mt-1.5 text-[14px] leading-relaxed text-ink-2">{{ step.body }}</p>
                <div class="mt-3 flex flex-wrap gap-1.5">
                  <span v-for="c in step.chips" :key="c" class="rounded-full border border-line bg-white/70 px-2.5 py-0.5 text-[12px] text-ink-2">{{ c }}</span>
                </div>
              </div>
            </Transition>

            <div class="mt-6 flex items-center gap-3">
              <div class="flex gap-1.5" aria-hidden="true">
                <span v-for="(s, i) in STEPS" :key="i" class="h-1.5 rounded-full transition-all duration-500 ease-[var(--ease-spring)]" :class="i === tourState.step ? 'w-6 bg-brand' : 'w-1.5 bg-line'" />
              </div>
              <button v-if="tourState.step > 0" class="btn-ghost btn-sm ml-auto" @click="tourState.step--">上一步</button>
              <button v-if="!last" class="btn-primary" :class="{ 'ml-auto': tourState.step === 0 }" @click="next">下一步<Icon name="arrow-right" :size="15" /></button>
              <template v-else>
                <button class="btn-glass btn-sm" @click="finish">先逛逛</button>
                <button class="btn-primary" @click="tryIt"><Icon name="github" :size="15" />试试 GitHub 搜索</button>
              </template>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.tour-hero {
  background: linear-gradient(135deg, #e8f0ff, #f4f8ff 55%, #dfeaff);
  transition: background 0.6s;
}
.tour-hero[data-step='1'] {
  background: linear-gradient(135deg, #e6f6ff, #f4fbff 55%, #dcefff);
}
.tour-hero[data-step='2'] {
  background: linear-gradient(135deg, #eeeaff, #f6f4ff 55%, #e4e6ff);
}
.tour-blob {
  position: absolute;
  border-radius: 50%;
  filter: blur(28px);
  opacity: 0.55;
  animation: drift 14s ease-in-out infinite alternate;
}
.tour-blob.a {
  width: 180px;
  height: 180px;
  left: -40px;
  top: -60px;
  background: rgb(90 162 255 / 0.6);
}
.tour-blob.b {
  width: 150px;
  height: 150px;
  right: -30px;
  bottom: -70px;
  background: rgb(30 86 214 / 0.35);
  animation-delay: -6s;
}
.tour-ic {
  animation: float 3.2s ease-in-out infinite;
}
.tour-ic-enter-active,
.tour-ic-leave-active {
  transition: transform 0.45s var(--ease-spring), opacity 0.3s;
}
.tour-ic-enter-from {
  opacity: 0;
  transform: scale(0.6) rotate(-12deg);
}
.tour-ic-leave-to {
  opacity: 0;
  transform: scale(0.8) rotate(10deg);
}
.tour-txt-enter-active,
.tour-txt-leave-active {
  transition: transform 0.35s var(--ease-out-expo), opacity 0.25s;
}
.tour-txt-enter-from {
  opacity: 0;
  transform: translateX(18px);
}
.tour-txt-leave-to {
  opacity: 0;
  transform: translateX(-18px);
}
@media (prefers-reduced-motion: reduce) {
  .tour-blob,
  .tour-ic {
    animation: none;
  }
}
</style>
