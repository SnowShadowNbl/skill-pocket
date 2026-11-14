<script setup>
import { computed, ref, watch } from 'vue'
import { api } from '../../api'
import { toast } from '../../composables/toast'
import { afterDays, fromBj, toBj } from '../composables/time'
import ADateTime from './ADateTime.vue'

// 首页置顶设置：权重（1~100，越大越靠前）+ 可选的开始 / 结束时间（北京时间，到期自动失效）
//   <APinDialog :open :item="{ id, name, pin: { weight, starts_at, ends_at, state, state_label } }" @close @saved="(row) => …" />
const props = defineProps({ open: Boolean, item: { type: Object, default: null } })
const emit = defineEmits(['close', 'saved'])
const weight = ref('50')
const starts = ref('')
const ends = ref('')
const busy = ref(false)
const err = ref('')

watch(() => [props.open, props.item?.id], () => {
  if (!props.open || !props.item) return
  const p = props.item.pin || {}
  weight.value = String(p.weight || 50)
  starts.value = toBj(p.starts_at)
  ends.value = toBj(p.ends_at)
  err.value = ''
}, { immediate: true })

const isPinned = computed(() => (props.item?.pin?.weight || 0) > 0)
const PRESETS = [['1 天', 1], ['7 天', 7], ['30 天', 30]]
function preset(n) {
  starts.value = afterDays(0)
  ends.value = afterDays(n)
}
function forever() {
  starts.value = ''
  ends.value = ''
}

async function save(w) {
  busy.value = true
  err.value = ''
  try {
    const body = w === 0 ? { weight: 0 } : { weight: Math.max(1, Math.min(100, Number(weight.value) || 0)), starts_at: fromBj(starts.value), ends_at: fromBj(ends.value) }
    const row = await api(`/api/admin/items/${props.item.id}/pin`, { method: 'PUT', body })
    toast(w === 0 ? '已取消置顶' : row.pin?.state === 'scheduled' ? '已设置，未到开始时间' : '已置顶到首页', 'success')
    emit('saved', row)
    emit('close')
  } catch (e) {
    err.value = e.message
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <Transition name="fade">
    <div v-if="open && item" class="fixed inset-0 z-50 grid place-items-end bg-ink/35 sm:place-items-center sm:px-4" @click.self="emit('close')" @keydown.esc="emit('close')">
      <form class="card w-full rounded-b-none p-5 shadow-[0_20px_50px_-20px_rgba(15,29,51,.35)] sm:max-w-[440px] sm:rounded-b-lg sm:p-6" role="dialog" aria-modal="true" aria-label="首页置顶" @submit.prevent="save()">
        <h2 class="m-0 text-base font-semibold">首页置顶</h2>
        <p class="m-0 mt-1 truncate text-[13px] text-mute">{{ item.name }}<template v-if="item.pin?.state_label && item.pin.state !== 'none'"> · {{ item.pin.state_label }}</template></p>
        <label class="mt-4 block text-[13px] text-ink-2">权重（1~100，越大越靠前）
          <input v-model="weight" type="number" min="1" max="100" class="input mt-1.5 w-28 tabular-nums" aria-label="置顶权重" />
        </label>
        <div class="mt-4 grid gap-3 sm:grid-cols-2">
          <div class="text-[13px] text-ink-2">开始时间<div class="mt-1.5"><ADateTime v-model="starts" placeholder="立即" /></div></div>
          <div class="text-[13px] text-ink-2">结束时间<div class="mt-1.5"><ADateTime v-model="ends" placeholder="不限" :min="starts" /></div></div>
        </div>
        <div class="mt-3 flex flex-wrap gap-1.5">
          <button v-for="p in PRESETS" :key="p[0]" type="button" class="btn btn-sm" @click="preset(p[1])">{{ p[0] }}</button>
          <button type="button" class="btn btn-sm" @click="forever">长期</button>
        </div>
        <p v-if="err" class="m-0 mt-3 text-[13px] text-bad">{{ err }}</p>
        <div class="mt-5 flex items-center gap-2">
          <button v-if="isPinned" type="button" class="btn btn-danger" :disabled="busy" @click="save(0)">取消置顶</button>
          <span class="ml-auto flex gap-2">
            <button type="button" class="btn" @click="emit('close')">取消</button>
            <button class="btn btn-primary" :disabled="busy">{{ busy ? '保存中…' : '保存' }}</button>
          </span>
        </div>
      </form>
    </div>
  </Transition>
</template>
