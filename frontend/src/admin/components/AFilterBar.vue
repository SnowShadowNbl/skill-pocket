<script setup>
import { ref } from 'vue'
import Icon from '../../components/Icon.vue'
import ADateRange from './ADateRange.vue'
import ASelect from './ASelect.vue'
import ASwitch from './ASwitch.vue'

// 筛选栏：条件由 useQueryFilters 的 filters 驱动（改动会同步到地址栏）。手机上只露出搜索框和「筛选」按钮，其余条件点开折叠面板
//   <AFilterBar :filters="filters" :fields="[{ key, type: 'search' | 'select' | 'daterange' | 'switch', label, options?, placeholder?, searchable?（下拉可搜索）, counts?（日期区间显示每天条目数）, fieldKey?（日期类型所在的筛选键） }]" :active-count="n" @reset="reset">
//     <template #extra>页面特有的控件</template>
//   </AFilterBar>
const props = defineProps({
  filters: { type: Object, required: true },
  fields: { type: Array, required: true },
  activeCount: { type: Number, default: 0 },
})
defineEmits(['reset'])
const open = ref(false)
const search = props.fields.find((f) => f.type === 'search')
const others = props.fields.filter((f) => f.type !== 'search')
const set = (k, v) => { props.filters[k] = v }
</script>

<template>
  <div class="border-b border-line p-3.5">
    <div class="flex flex-wrap items-center gap-2.5">
      <label v-if="search" class="relative min-w-0 flex-1 sm:min-w-[240px] sm:max-w-sm">
        <Icon name="search" :size="15" class="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-mute" />
        <input :value="filters[search.key]" type="search" class="input pl-9" :placeholder="search.placeholder || search.label" :aria-label="search.label" @input="set(search.key, $event.target.value)" />
      </label>
      <button v-if="others.length" type="button" class="btn h-9 sm:hidden" :aria-expanded="open" @click="open = !open">
        筛选<b v-if="activeCount" class="grid h-[18px] min-w-[18px] place-items-center rounded-full bg-primary px-1 text-[11px] font-semibold text-white">{{ activeCount }}</b>
      </button>
      <div class="hidden flex-wrap items-center gap-2.5 sm:flex">
        <template v-for="f in others" :key="f.key">
          <div v-if="f.type === 'select'" class="w-[150px]"><ASelect :model-value="filters[f.key]" :options="f.options" :label="f.label" :searchable="f.searchable" @update:model-value="set(f.key, $event)" /></div>
          <div v-else-if="f.type === 'daterange'" class="w-[230px]"><ADateRange :model-value="filters[f.key]" :counts="f.counts ?? false" :field="f.fieldKey ? filters[f.fieldKey] : undefined" :placeholder="f.label" @update:model-value="set(f.key, $event)" /></div>
          <ASwitch v-else-if="f.type === 'switch'" :model-value="filters[f.key]" :label="f.label" @update:model-value="set(f.key, $event)" />
        </template>
        <slot name="extra" />
      </div>
      <button v-if="activeCount" type="button" class="btn h-9 shrink-0 text-mute" @click="$emit('reset')"><Icon name="refresh" :size="14" />重置</button>
    </div>
    <div v-if="open && others.length" class="mt-2.5 grid gap-2.5 sm:hidden">
      <template v-for="f in others" :key="f.key">
        <ASelect v-if="f.type === 'select'" :model-value="filters[f.key]" :options="f.options" :label="f.label" :searchable="f.searchable" @update:model-value="set(f.key, $event)" />
        <ADateRange v-else-if="f.type === 'daterange'" :model-value="filters[f.key]" :counts="f.counts ?? false" :field="f.fieldKey ? filters[f.fieldKey] : undefined" :placeholder="f.label" @update:model-value="set(f.key, $event)" />
        <ASwitch v-else-if="f.type === 'switch'" :model-value="filters[f.key]" :label="f.label" class="justify-between" @update:model-value="set(f.key, $event)" />
      </template>
      <slot name="extra" />
    </div>
  </div>
</template>
