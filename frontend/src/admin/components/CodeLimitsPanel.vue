<script setup>
import { computed, ref, watch } from 'vue'
import { api, isCancelled } from '../../api'
import { toast } from '../../composables/toast'
import { onActionError } from '../composables/handled'
import { askReason } from '../composables/reason'
import { can } from '../composables/usePermissions'
import { callVerified } from '../composables/verify'

// 验证码限制：发送量、被限频次数、发得最多的邮箱和 IP；阈值可以改（要二次验证），立即生效
const days = ref(7)
const data = ref(null)
const draft = ref({})
const busy = ref(false)
const canWrite = can('resources', 'w')
const DAYS = [[1, '24 小时'], [7, '7 天'], [30, '30 天']]
const KIND = { email: '邮箱', ip: 'IP', account: '账号' }
const KEYS = computed(() => (data.value ? Object.keys(data.value.threshold) : []))
const dirty = computed(() => data.value && KEYS.value.some((k) => Number(draft.value[k]) !== data.value.threshold[k]))
const bad = computed(() => data.value && KEYS.value.some((k) => { const v = Number(draft.value[k]); const [lo, hi] = data.value.ranges[k]; return !(Number.isInteger(v) && v >= lo && v <= hi) }))

async function load() {
  try {
    const d = await api(`/api/admin/code-limits?days=${days.value}`)
    data.value = d
    draft.value = { ...d.threshold }
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  }
}
watch(days, load, { immediate: true })

async function save() {
  const changed = Object.fromEntries(KEYS.value.filter((k) => Number(draft.value[k]) !== data.value.threshold[k]).map((k) => [k, Number(draft.value[k])]))
  const reason = await askReason({ title: '修改验证码限制', impact: '新的限制立即生效；需要先验证你的邮箱', templates: ['有人在刷验证码，收紧限制', '误伤正常用户，放宽限制'], danger: true, okText: '保存' })
  if (reason === null) return
  busy.value = true
  try {
    const r = await callVerified('/api/admin/code-limits/threshold', { method: 'PUT', body: { ...changed, reason } }, { action: 'code_limit', title: '修改验证码限制' })
    data.value.threshold = r.threshold
    draft.value = { ...r.threshold }
    toast('已保存', 'success')
  } catch (e) {
    if (e?.code === 'bad_range') toast('有的数值超出允许范围', 'error')
    else await onActionError(e)
  } finally {
    busy.value = false
  }
}
const rows = (title, list) => ({ title, list })
</script>

<template>
  <div>
    <div class="mt-3"><div class="seg inline-flex"><button v-for="d in DAYS" :key="d[0]" :class="{ on: days === d[0] }" @click="days = d[0]">{{ d[1] }}</button></div></div>
    <div v-if="!data" class="skeleton mt-3 h-60" />
    <template v-else>
      <ul class="m-0 mt-3 grid list-none grid-cols-2 gap-3.5 p-0">
        <li class="card px-[18px] py-3.5"><p class="m-0 text-[13px] text-mute">发送验证码</p><b class="mt-1 block text-2xl tabular-nums">{{ data.stats.sent }}</b></li>
        <li class="card px-[18px] py-3.5" :class="data.stats.limited ? 'border-warn/50 bg-warn-soft' : ''"><p class="m-0 text-[13px]" :class="data.stats.limited ? 'text-warn' : 'text-mute'">被限频</p><b class="mt-1 block text-2xl tabular-nums" :class="{ 'text-warn': data.stats.limited }">{{ data.stats.limited }}</b></li>
      </ul>

      <section class="card mt-3.5">
        <div class="card-hd"><h2>限制</h2></div>
        <form class="card-bd grid gap-3 sm:grid-cols-2 lg:grid-cols-[repeat(4,1fr)_auto]" @submit.prevent="save">
          <label v-for="k in KEYS" :key="k" class="block text-xs text-mute">{{ data.labels[k] }}
            <input v-model="draft[k]" type="number" class="input mt-1 tabular-nums" :min="data.ranges[k][0]" :max="data.ranges[k][1]" :disabled="!canWrite" :aria-label="data.labels[k]" />
            <span class="mt-0.5 block text-[11px]">{{ data.ranges[k][0] }}–{{ data.ranges[k][1] }}</span>
          </label>
          <button v-if="canWrite" class="btn btn-primary self-start sm:mt-[18px]" :disabled="!dirty || bad || busy">保存</button>
        </form>
      </section>

      <div class="mt-3.5 grid gap-3.5 lg:grid-cols-2">
        <section v-for="s in [rows('被限频最多', data.limited), rows('发送最多', data.top_senders)]" :key="s.title" class="card">
          <div class="card-hd"><h2>{{ s.title }}</h2></div>
          <p v-if="!s.list.length" class="m-0 px-[18px] py-6 text-center text-[13px] text-mute">没有</p>
          <ul v-else class="m-0 list-none p-0"><li v-for="r in s.list" :key="r.kind + r.key" class="flex items-center gap-2 border-b border-dashed border-line px-[18px] py-2 text-[13px] last:border-0"><span class="tag tag-gray">{{ KIND[r.kind] || r.kind }}</span><b class="min-w-0 flex-1 font-mono text-xs break-all">{{ r.key }}</b><span class="tabular-nums">{{ r.count }} 次</span></li></ul>
        </section>
      </div>
    </template>
  </div>
</template>
