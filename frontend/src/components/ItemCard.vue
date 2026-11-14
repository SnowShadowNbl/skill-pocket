<script setup>
import { computed, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import CompareToggle from './CompareToggle.vue'
import CoverImage from './CoverImage.vue'
import Icon from './Icon.vue'
import FavoriteButton from './FavoriteButton.vue'
import StatusBadge from './StatusBadge.vue'
import { formatStars } from '../api'
import { kindStyle } from '../categoryStyle'
import { compareState, fromItem } from '../composables/compare'
import { isFav } from '../composables/favorites'
import { toast } from '../composables/toast'

// v3.0 卡片：封面用原图（没有图的由 AI 按主题色画）+ 悬停 3D 倾斜、光斑、扫光、标题下划线；
// 底栏是分类、来源、星标和收藏小爱心。手机一行两个时隐藏仓库名和分类
const props = defineProps({
  item: Object,
  index: { type: Number, default: 0 },
  base: { type: String, default: '' },
  showStatus: Boolean, // 「我提交的」：显示审核 / 处理状态
  dense: Boolean, // 手机上一行两个的紧凑卡片
  noCompare: Boolean, // 不显示「对比」勾选框（如收藏页的多选模式）
})
defineEmits(['fav'])
const route = useRoute()
// 已下线：不进详情页，盖「原文已下线」水印；还在收藏里的可以取消收藏
const offline = computed(() => !!props.item.offline)
const KIND_SHORT = { agent_skill: 'Skill', model: 'Model', app: 'App', dev: 'Dev', demo: 'Demo' }
const repoLabel = computed(() => {
  const r = props.item.repo_full_name
  if (!r) return ''
  return props.item.sub_path ? `${r} / ${props.item.sub_path.split('/').pop()}` : r
})
const sourceLabel = computed(() => (props.item.source === 'auto' ? '采集' : props.item.uploader ? `${props.item.uploader.nickname} 上传` : '上传'))

const copied = ref(false)
async function copyRepo() {
  try {
    await navigator.clipboard.writeText(props.item.repo_full_name)
  } catch {}
  copied.value = true
  toast(`已复制仓库名 ${props.item.repo_full_name}`)
  setTimeout(() => (copied.value = false), 1400)
}
</script>

<template>
  <component
    :is="offline ? 'div' : RouterLink"
    v-reveal="index"
    v-tilt
    :to="offline ? undefined : { path: `${base}/items/${item.id}`, query: route.query }"
    class="icard group relative flex min-w-0 flex-col overflow-hidden rounded-lg border border-line bg-panel"
    :class="offline ? 'cursor-not-allowed select-none' : 'cursor-pointer'"
    :aria-disabled="offline || undefined"
    :title="offline ? `原文已下线，不可点击${item.offline_reason ? '：' + item.offline_reason : ''}` : undefined"
  >
    <div class="relative border-b border-line-2 bg-brand-soft" :class="{ 'grayscale opacity-60': offline }">
      <div class="relative aspect-[16/9.5] overflow-hidden sm:aspect-[16/8.5]">
        <CoverImage :src="item.cover_url" :name="item.name" :category="item.category" float :delay="index" class="cv-img absolute inset-0 h-full w-full" />
        <span class="cv-scan" />
        <!-- v3.3 口碑（好用度）：有人打过分才显示 -->
        <span v-if="item.rating_count" class="absolute right-1.5 bottom-1.5 z-[5] inline-flex items-center gap-0.5 rounded-full bg-white/92 px-1.5 font-mono text-[10.5px] leading-[18px] font-semibold text-ink shadow-[0_2px_8px_-4px_rgb(11_47_122/0.5)] backdrop-blur sm:right-2 sm:bottom-2" :title="`口碑 ${item.rating_avg} 分 · ${item.rating_count} 人评`">
          <svg viewBox="0 0 24 24" class="h-[11px] w-[11px] text-amber-400"><path fill="currentColor" d="M12 2.5l2.9 6 6.6.9-4.8 4.6 1.2 6.5L12 17.4l-5.9 3.1 1.2-6.5-4.8-4.6 6.6-.9z" /></svg>{{ item.rating_avg }}
        </span>
      </div>
      <CompareToggle
        v-if="compareState.mode && !offline && !noCompare && (!item.status || item.status === 'published')"
        :entry="fromItem(item)"
        class="absolute top-1.5 right-1.5 z-10 sm:top-2 sm:right-2"
      />
      <span class="absolute top-1.5 left-1.5 z-[5] flex gap-1 sm:top-2 sm:left-2">
        <span v-if="item.pinned" class="rounded-[3px] bg-brand px-1.5 font-mono text-[10px] leading-4 text-white" title="站长推荐">置顶</span>
        <span v-if="item.in_use" class="rounded-[3px] bg-ok px-1.5 text-[10px] leading-4 font-medium text-white" title="近 14 天写过使用日志">最近在用</span>
        <span v-if="item.kind" class="rounded-[3px] border px-1.5 font-mono text-[10px] leading-4" :class="kindStyle(item.kind.key).cls" :title="item.kind.name">
          {{ KIND_SHORT[item.kind.key] || item.kind.name }}
        </span>
      </span>
    </div>

    <div class="flex min-w-0 flex-1 flex-col gap-[3px] px-2.5 pt-2 pb-2.5 sm:gap-1 sm:px-3 sm:pt-[11px] sm:pb-3" :class="{ 'opacity-55': offline }">
      <h3 class="flex min-w-0 items-center gap-2">
        <span class="ttl-u min-w-0 truncate text-[14px] leading-5 font-semibold tracking-[-0.01em] sm:text-[15px] sm:leading-[22px]">{{ item.name }}</span>
      </h3>
      <span v-if="repoLabel" class="flex min-w-0 items-center gap-1.5 font-mono text-[11px] leading-4 text-mute max-sm:hidden">
        <span class="truncate">{{ repoLabel }}</span>
        <button
          type="button"
          class="grid h-5 w-5 shrink-0 cursor-pointer place-items-center rounded-[4px] transition-[opacity,transform,background-color,color] duration-300 hover:bg-brand-soft hover:text-brand [@media(hover:hover)]:-translate-x-1 [@media(hover:hover)]:opacity-0 [@media(hover:hover)]:group-hover:translate-x-0 [@media(hover:hover)]:group-hover:opacity-100"
          :class="{ '!translate-x-0 text-brand !opacity-100': copied }"
          aria-label="复制仓库名"
          @click.stop.prevent="copyRepo"
        ><Icon :name="copied ? 'check' : 'copy'" :size="12" /></button>
      </span>
      <StatusBadge v-if="showStatus" :item="item" />
      <p class="mt-px line-clamp-3 min-h-[54px] text-[12.5px] leading-[18px] text-ink-2 sm:line-clamp-2 sm:min-h-10 sm:text-[13px] sm:leading-5">
        <span v-if="item.ai_status === 'pending' || item.ai_status === 'running'" class="inline-flex items-center gap-1.5 text-brand">
          <Icon name="sparkles" :size="13" class="animate-pulse" />AI 提炼中…
        </span>
        <template v-else>{{ item.summary || '暂无描述' }}</template>
      </p>
      <p v-if="item.match?.reason" class="flex items-start gap-1 rounded-md bg-brand-soft px-2 py-1 text-[12px] leading-relaxed text-brand">
        <Icon name="sparkles" :size="12" class="mt-0.5 shrink-0" />{{ item.match.reason }}
      </p>
      <div class="mt-auto flex items-center gap-1.5 border-t border-dashed border-line-2 pt-1.5 font-mono text-[11px] leading-4 text-mute sm:gap-2 sm:pt-2">
        <span class="min-w-0 truncate max-sm:hidden">{{ item.category?.group_name ? `${item.category.group_name} / ` : '' }}{{ item.category?.name }}</span>
        <span class="inline-flex min-w-0 shrink-0 items-center gap-1 max-sm:truncate">
          <span class="h-[5px] w-[5px] shrink-0 rounded-full" :class="item.source === 'auto' ? 'bg-sky' : 'bg-brand'" />{{ sourceLabel }}
        </span>
        <span v-if="item.stars != null" class="ml-auto font-medium whitespace-nowrap text-ink tabular-nums">★ {{ formatStars(item.stars) }}</span>
        <FavoriteButton v-if="!offline || isFav(item)" :item="item" variant="mini" :class="{ 'ml-auto': item.stars == null }" @change="(v) => $emit('fav', v)" />
      </div>
    </div>

    <!-- 已下线水印 -->
    <div v-if="offline" class="pointer-events-none absolute inset-0 grid place-items-center overflow-hidden" aria-hidden="true">
      <div class="watermark absolute inset-0" />
      <div class="relative flex flex-col items-center gap-1 rounded-lg bg-ink/75 px-4 py-2.5 text-center text-white shadow-lg backdrop-blur-sm max-sm:px-1.5 max-sm:py-1">
        <span class="flex items-center gap-1.5 text-[14px] font-semibold max-sm:text-[10.5px]"><Icon name="alert" :size="15" class="max-sm:hidden" />原文已下线<span class="max-sm:hidden">，不可点击</span></span>
        <span v-if="item.offline_reason" class="max-w-[16rem] text-[11.5px] leading-snug text-white/80 max-sm:hidden">{{ item.offline_reason }}</span>
      </div>
    </div>
  </component>
</template>

<style scoped>
.watermark {
  background-image: repeating-linear-gradient(-28deg, transparent 0 46px, rgb(100 116 139 / 0.13) 46px 48px);
  background-color: rgb(241 245 249 / 0.35);
}
.watermark::after {
  content: '原文已下线  原文已下线  原文已下线  原文已下线  原文已下线  原文已下线';
  position: absolute;
  inset: -40%;
  display: flex;
  align-items: center;
  justify-content: center;
  transform: rotate(-28deg);
  font-size: 18px;
  font-weight: 800;
  letter-spacing: 0.3em;
  line-height: 3.2;
  color: rgb(100 116 139 / 0.2);
  word-break: break-all;
  white-space: normal;
}
</style>
