<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { api, formatStars, formatTime } from '../api'
import AiTag from '../components/AiTag.vue'
import Icon from '../components/Icon.vue'
import { toast } from '../composables/toast'

// 对比结果：结论与推荐 → 同类的多维度对比表 / 不同类的说明 → 每个条目的上手方法。结果可以分享
const props = defineProps({ cid: { type: String, required: true } })
const router = useRouter()
const run = ref(null)
const error = ref('')
let timer

const byCode = computed(() => Object.fromEntries((run.value?.subjects || []).map((s) => [s.code, s])))
const res = computed(() => run.value?.result || {})
const sameGroups = computed(() => (res.value.groups || []).filter((g) => g.type === 'same'))
const diffGroups = computed(() => (res.value.groups || []).filter((g) => g.type === 'different'))
const name = (code) => byCode.value[code]?.name || code
const subjectLink = (s) => (s.item_id ? { internal: `/compare/${props.cid}/items/${s.item_id}` } : { external: s.html_url })

async function load() {
  clearTimeout(timer)
  try {
    run.value = await api(`/api/compare/${props.cid}`)
    error.value = ''
    if (run.value.status === 'running') timer = setTimeout(load, 1500)
  } catch (e) {
    error.value = e.message
  }
}

async function share() {
  const url = `${location.origin}/compare/${props.cid}`
  try {
    await navigator.clipboard.writeText(url)
    toast('链接已复制，发给朋友就能看到这份对比', 'success')
  } catch {
    toast(url, 'info', 6000)
  }
}

watch(() => props.cid, load, { immediate: true })
onBeforeUnmount(() => clearTimeout(timer))
</script>

<template>
  <div class="mx-auto max-w-5xl pb-10">
    <button class="btn-ghost btn-sm -ml-2 mb-2" @click="router.back()"><Icon name="arrow-left" :size="16" />返回</button>
    <div class="flex flex-wrap items-center gap-2">
      <h1 class="text-[clamp(22px,4vw,30px)] leading-tight font-extrabold tracking-tight">AI 智能对比</h1>
      <AiTag v-if="run?.model" :model="run.model" />
      <button v-if="run?.status === 'done'" class="btn-glass btn-sm ml-auto" @click="share"><Icon name="link" :size="15" />分享这份对比</button>
    </div>

    <p v-if="error" class="mt-4 flex items-center gap-2 rounded-2xl bg-danger-soft p-3.5 text-sm text-danger" role="alert"><Icon name="alert" :size="16" />{{ error }}</p>

    <!-- 参与对比的条目 -->
    <ul v-if="run" class="mt-4 grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-6">
      <li v-for="s in run.subjects" :key="s.code" class="panel flex flex-col gap-1 p-3">
        <span class="flex items-center gap-1.5">
          <b class="grid h-6 w-6 shrink-0 place-items-center rounded-lg bg-brand text-[12px] font-extrabold text-white">{{ s.code }}</b>
          <span class="tag h-5 px-1.5 text-[11px]" :class="s.source === 'site' ? 'bg-ok-soft text-ok' : 'bg-white/80 text-ink-2'">{{ s.source === 'site' ? '本站' : 'GitHub' }}</span>
        </span>
        <RouterLink v-if="subjectLink(s).internal" :to="subjectLink(s).internal" class="line-clamp-2 font-semibold break-words hover:text-brand">{{ s.name }}</RouterLink>
        <a v-else :href="subjectLink(s).external" target="_blank" rel="noopener" class="line-clamp-2 font-semibold break-words hover:text-brand">{{ s.name }}</a>
        <span class="truncate text-[11.5px] text-mute">{{ s.repo }}</span>
        <span v-if="s.stars != null" class="mt-auto flex items-center gap-1 text-[12px] text-ink-2 tabular-nums"><Icon name="star" :size="12" class="fill-amber-400 text-amber-400" />{{ formatStars(s.stars) }}</span>
      </li>
    </ul>

    <!-- 分析中 -->
    <div v-if="!run || run.status === 'running'" class="mt-5" aria-live="polite">
      <p class="flex items-center gap-2 text-[14px] text-brand"><Icon name="sparkles" :size="16" class="animate-pulse" />{{ run?.stage || '正在准备…' }}</p>
      <p class="mt-1 text-[12.5px] text-mute">AI 会先判断哪些是同一类，再从定位、核心能力、适用场景、上手难度、运行环境、活跃度、成本、许可证、局限等维度对比，通常需要 20~40 秒。</p>
      <div class="mt-4 space-y-3"><div class="skeleton-bar h-24 rounded-2xl" /><div class="skeleton-bar h-64 rounded-2xl" /></div>
    </div>

    <p v-else-if="run.status === 'failed'" class="mt-5 flex items-center gap-2 rounded-2xl bg-danger-soft p-3.5 text-sm text-danger" role="alert">
      <Icon name="alert" :size="16" />{{ run.error || '对比失败' }}，稍后再试
    </p>

    <template v-else>
      <!-- 结论与推荐 -->
      <section class="panel mt-5 p-5">
        <p class="flex items-start gap-2 text-[16px] leading-relaxed font-semibold"><Icon name="sparkles" :size="18" class="mt-1 shrink-0 text-brand" />{{ res.summary }}</p>
        <div v-if="res.recommendations?.length" class="mt-4 grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
          <div v-for="(r, i) in res.recommendations" :key="i" class="rounded-2xl border border-brand/15 bg-brand-soft/50 p-3.5">
            <p class="text-[12.5px] text-ink-2">{{ r.scenario }}</p>
            <p class="mt-0.5 flex items-center gap-1.5 font-bold"><Icon name="check" :size="15" class="text-ok" />推荐 {{ r.id }} · {{ name(r.id) }}</p>
            <p class="mt-1 text-[13px] leading-relaxed text-ink-2">{{ r.reason }}</p>
          </div>
        </div>
        <ul v-if="res.warnings?.length" class="mt-4 space-y-1.5">
          <li v-for="(w, i) in res.warnings" :key="i" class="flex items-start gap-2 rounded-xl bg-warn-soft px-3 py-2 text-[13px] text-warn">
            <Icon name="alert" :size="15" class="mt-0.5 shrink-0" /><span><b>{{ w.id }} · {{ name(w.id) }}：</b>{{ w.text }}</span>
          </li>
        </ul>
      </section>

      <!-- 同类：多维度对比表 -->
      <section v-for="(g, gi) in sameGroups" :key="'s' + gi" class="panel mt-4 overflow-hidden">
        <h2 class="flex flex-wrap items-center gap-2 px-5 pt-4 pb-3 text-[16px] font-bold">
          <span class="tag bg-ok-soft text-ok">同类</span>{{ g.title || '同一类工具' }}
          <span class="text-[13px] font-normal text-mute">{{ g.ids.map((c) => `${c} ${name(c)}`).join(' / ') }}</span>
        </h2>
        <div class="overflow-x-auto">
          <table class="w-full min-w-[560px] border-collapse text-[13px]">
            <thead>
              <tr class="border-y border-line bg-white/50">
                <th class="sticky left-0 z-10 w-28 bg-white/90 px-4 py-2.5 text-left font-medium text-mute backdrop-blur">维度</th>
                <th v-for="c in g.ids" :key="c" class="px-4 py-2.5 text-left font-semibold">{{ c }} · {{ name(c) }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="d in g.dimensions" :key="d.name" class="border-b border-line last:border-0">
                <th class="sticky left-0 z-10 bg-white/90 px-4 py-2.5 text-left align-top font-medium text-ink-2 backdrop-blur">{{ d.name }}</th>
                <td v-for="c in g.ids" :key="c" class="px-4 py-2.5 align-top leading-relaxed" :class="{ 'bg-ok-soft/60': d.better === c }">
                  {{ d.values[c] || '—' }}
                  <span v-if="d.better === c" class="mt-1 flex w-fit items-center gap-0.5 rounded-md bg-ok px-1.5 text-[11px] font-semibold text-white"><Icon name="check" :size="11" />更好</span>
                </td>
              </tr>
              <tr v-if="!g.dimensions.length"><td :colspan="g.ids.length + 1" class="px-4 py-6 text-center text-mute">AI 没有给出维度对比</td></tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- 不同类：说明各自作用 -->
      <section v-if="diffGroups.length" class="mt-4 grid gap-3 sm:grid-cols-2">
        <div v-for="(g, gi) in diffGroups" :key="'d' + gi" class="panel p-4">
          <p class="flex flex-wrap items-center gap-2">
            <span class="tag bg-white/80 text-ink-2">类型不同 · 作用不同</span>
            <b>{{ g.ids.map((c) => `${c} ${name(c)}`).join('、') }}</b>
          </p>
          <p v-if="g.title" class="mt-2 text-[13.5px] font-medium">{{ g.title }}</p>
          <p v-if="g.note" class="mt-1 text-[13px] leading-relaxed text-ink-2">{{ g.note }}</p>
        </div>
      </section>

      <!-- 上手方法 -->
      <section v-if="Object.keys(res.usage || {}).length" class="panel mt-4 p-5">
        <h2 class="section-title mb-3">怎么用</h2>
        <div class="grid gap-4 sm:grid-cols-2">
          <div v-for="(steps, code) in res.usage" :key="code">
            <p class="font-semibold">{{ code }} · {{ name(code) }}</p>
            <ol class="mt-1.5 list-decimal space-y-1 pl-5 text-[13px] leading-relaxed text-ink-2"><li v-for="(st, i) in steps" :key="i">{{ st }}</li></ol>
          </div>
        </div>
      </section>

      <p class="mt-4 text-xs text-mute">对比时间 {{ formatTime(run.finished_at || run.created_at) }} · AI 只依据收录资料和仓库介绍分析，资料没提到的会写「资料未提及」</p>
    </template>

    <RouterView v-slot="{ Component }">
      <Transition name="sheet">
        <component :is="Component" v-if="Component" />
      </Transition>
    </RouterView>
  </div>
</template>
