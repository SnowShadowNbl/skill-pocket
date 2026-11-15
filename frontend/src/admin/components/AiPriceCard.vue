<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../../api'
import { confirmDialog } from '../../composables/dialog'
import { toast } from '../../composables/toast'
import ASwitch from './ASwitch.vue'

// v3.3.89 AI 单价表（元 / 百万 token）：每次调用按当时的单价记下「按最高价」「按实际时段」两种成本
const COLS = [['in_peak', '输入 · 高峰'], ['in_idle', '输入 · 闲时'], ['hit_peak', '缓存命中 · 高峰'], ['hit_idle', '缓存命中 · 闲时'],
  ['out_peak', '输出 · 高峰'], ['out_idle', '输出 · 闲时']]
const data = ref(null)
const rows = ref([])
const peak = ref('')
const weekdaysOnly = ref(true)
const busy = ref(false)

function fill(d) {
  data.value = d
  rows.value = Object.entries(d.models).map(([name, p]) => ({ name, ...Object.fromEntries(COLS.map(([k]) => [k, String(p[k])])) }))
  peak.value = (d.peak || []).map(([a, b]) => `${a}-${b}`).join(', ')
  weekdaysOnly.value = d.peak_weekdays_only
}
onMounted(async () => {
  try {
    fill(await api('/api/admin/ai/prices'))
  } catch (e) {
    toast(e.message, 'error')
  }
})

const parsedPeak = computed(() => peak.value.split(/[,，\s]+/).filter(Boolean).map((w) => w.split('-').map(Number)))
const peakOk = computed(() => parsedPeak.value.every((w) => w.length === 2 && w.every((n) => Number.isFinite(n)) && w[0] >= 0 && w[0] < w[1] && w[1] <= 24))
const numsOk = computed(() => rows.value.every((r) => r.name.trim() && COLS.every(([k]) => r[k] !== '' && Number(r[k]) >= 0)))

const addRow = () => rows.value.push({ name: '', ...Object.fromEntries(COLS.map(([k]) => [k, '0'])) })
const delRow = (i) => rows.value.splice(i, 1)

async function save() {
  busy.value = true
  try {
    const models = Object.fromEntries(rows.value.map((r) => [r.name.trim(), Object.fromEntries(COLS.map(([k]) => [k, Number(r[k])]))]))
    fill(await api('/api/admin/ai/prices', { method: 'PUT', body: { models, peak: parsedPeak.value, peak_weekdays_only: weekdaysOnly.value } }))
    toast('已保存，之后的调用按新单价记成本', 'success')
  } catch (e) {
    toast(e.message, 'error')
  } finally {
    busy.value = false
  }
}
async function restore() {
  if (!(await confirmDialog({ title: '恢复默认单价？', okText: '恢复' }))) return
  const d = data.value.defaults
  fill({ ...data.value, models: d.models, peak: d.peak, peak_weekdays_only: d.peak_weekdays_only })
}
</script>

<template>
  <section class="card">
    <div class="card-hd"><h2>AI 单价（元 / 百万 token）</h2></div>
    <div v-if="!data" class="card-bd"><div class="skeleton h-40" /></div>
    <template v-else>
      <div class="overflow-x-auto">
        <table class="tbl text-[12.5px]">
          <thead><tr><th>模型</th><th v-for="c in COLS" :key="c[0]" class="text-right whitespace-nowrap">{{ c[1] }}</th><th /></tr></thead>
          <tbody>
            <tr v-for="(r, i) in rows" :key="i">
              <td><input v-model="r.name" class="input !h-8 min-w-[150px] font-mono !text-[12.5px]" /></td>
              <td v-for="c in COLS" :key="c[0]"><input v-model="r[c[0]]" class="input !h-8 w-[84px] text-right tabular-nums !text-[12.5px]" inputmode="decimal" /></td>
              <td><button class="btn !h-8 !px-2 text-mute" :aria-label="`删除 ${r.name}`" @click="delRow(i)">×</button></td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="card-bd flex flex-wrap items-end gap-3 border-t border-line">
        <button class="btn h-9" @click="addRow">添加模型</button>
        <label class="text-xs text-mute">高峰时段（北京时间）
          <input v-model="peak" class="input mt-1 w-[160px]" :class="{ '!border-bad': !peakOk }" />
        </label>
        <ASwitch v-model="weekdaysOnly" label="只有工作日有高峰" />
        <div class="ml-auto flex gap-2">
          <button class="btn" @click="restore">恢复默认</button>
          <button class="btn btn-primary" :disabled="busy || !peakOk || !numsOk" @click="save">保存</button>
        </div>
      </div>
    </template>
  </section>
</template>
