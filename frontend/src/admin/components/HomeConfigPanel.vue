<script setup>
import { computed, ref } from 'vue'
import { api, isCancelled } from '../../api'
import { toast } from '../../composables/toast'
import { askReason } from '../composables/reason'
import { fromBj, toBj } from '../composables/time'
import { can } from '../composables/usePermissions'
import ADateTime from './ADateTime.vue'
import ASwitch from './ASwitch.vue'

// 首页运营位：公告横幅、搜索框轮播提示词、新手引导开关。只对网页端生效
const cfg = ref(null)
const draft = ref(null)
const busy = ref(false)
const canWrite = computed(() => can('operations', 'w'))
const LEVELS = [['info', '普通'], ['warn', '提醒'], ['success', '好消息']]

function fill(d) {
  cfg.value = d
  draft.value = {
    banner: { ...d.banner, starts_at: toBj(d.banner.starts_at), ends_at: toBj(d.banner.ends_at) },
    placeholders: d.search_placeholders.join('\n'),
    onboarding: !!d.onboarding_enabled,
  }
}
async function load() {
  try {
    fill(await api('/api/admin/home-config'))
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  }
}
load()

const list = computed(() => (draft.value ? draft.value.placeholders.split('\n').map((x) => x.trim()).filter(Boolean) : []))
const bad = computed(() => draft.value && (list.value.length > 10 || list.value.some((x) => x.length > 30) || (draft.value.banner.enabled && !draft.value.banner.text.trim())))
const dirty = computed(() => {
  if (!cfg.value) return false
  const b = cfg.value.banner
  const d = draft.value
  return d.banner.enabled !== b.enabled || d.banner.text !== b.text || d.banner.link !== b.link || d.banner.level !== b.level || d.banner.starts_at !== toBj(b.starts_at) || d.banner.ends_at !== toBj(b.ends_at) || list.value.join('\n') !== cfg.value.search_placeholders.join('\n') || d.onboarding !== !!cfg.value.onboarding_enabled
})

async function save() {
  const reason = await askReason({ title: '修改首页运营位', impact: '保存后网页端首页立即生效；横幅内容改了，关掉过横幅的用户会重新看到', templates: ['新功能上线通知', '活动宣传', '调整提示词'], okText: '保存' })
  if (reason === null) return
  busy.value = true
  try {
    const b = draft.value.banner
    const body = {
      reason,
      banner: { enabled: b.enabled, text: b.text.trim(), link: b.link.trim(), level: b.level, starts_at: fromBj(b.starts_at), ends_at: fromBj(b.ends_at) },
      search_placeholders: list.value,
      onboarding_enabled: draft.value.onboarding,
    }
    await api('/api/admin/home-config', { method: 'PUT', body })
    toast('已保存', 'success')
    await load()
  } catch (e) {
    toast(e.code === 'empty_banner' ? '开启横幅时文字不能为空' : e.code === 'bad_range' ? '结束时间要晚于开始时间' : e.code === 'bad_link' ? '链接只能是站内路径' : e.message, 'error')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div>
    <div v-if="!draft" class="skeleton mt-3 h-60" />
    <template v-else>
      <p class="m-0 mt-3 text-[13px] text-mute">只对网页端生效，小程序暂时不显示</p>
      <section class="card mt-3">
        <div class="card-hd"><h2>公告横幅</h2><span class="tag ml-2" :class="cfg.banner_live ? 'tag-ok' : 'tag-gray'">{{ cfg.banner_live ? '正在显示' : '没有显示' }}</span><span class="ml-auto"><ASwitch v-model="draft.banner.enabled" label="开启" :disabled="!canWrite" /></span></div>
        <div class="card-bd space-y-3">
          <label class="block text-xs text-mute">文字（最多 80 字）<input v-model="draft.banner.text" class="input mt-1" maxlength="80" :disabled="!canWrite" /></label>
          <label class="block text-xs text-mute">点开后去哪里（站内路径，可不填）<input v-model="draft.banner.link" class="input mt-1 font-mono" maxlength="300" placeholder="/categories" :disabled="!canWrite" /></label>
          <div><p class="m-0 mb-1.5 text-xs text-mute">样式</p><div class="seg"><button v-for="l in LEVELS" :key="l[0]" :class="{ on: draft.banner.level === l[0] }" :disabled="!canWrite" @click="draft.banner.level = l[0]">{{ l[1] }}</button></div></div>
          <div class="grid gap-3 sm:grid-cols-2">
            <div><p class="m-0 mb-1.5 text-xs text-mute">开始时间</p><ADateTime v-model="draft.banner.starts_at" placeholder="立即" /></div>
            <div><p class="m-0 mb-1.5 text-xs text-mute">结束时间</p><ADateTime v-model="draft.banner.ends_at" :min="draft.banner.starts_at" placeholder="不限" /></div>
          </div>
        </div>
      </section>
      <section class="card mt-3.5">
        <div class="card-hd"><h2>搜索框提示词</h2><span class="text-xs text-mute">一行一个，最多 10 个，每个最多 30 字；不填用内置的</span></div>
        <div class="card-bd"><textarea v-model="draft.placeholders" rows="5" class="input h-auto resize-y py-2" aria-label="搜索框提示词" :disabled="!canWrite" /><p v-if="list.length > 10 || list.some((x) => x.length > 30)" class="m-0 mt-1 text-xs text-bad">最多 10 个，每个最多 30 字</p></div>
      </section>
      <section class="card mt-3.5">
        <div class="card-hd"><h2>新手引导</h2><span class="ml-auto"><ASwitch v-model="draft.onboarding" label="首次访问时弹出" :disabled="!canWrite" /></span></div>
      </section>
      <div v-if="canWrite" class="mt-3.5 flex justify-end"><button class="btn btn-primary" :disabled="busy || !dirty || bad" @click="save">保存</button></div>
    </template>
  </div>
</template>
