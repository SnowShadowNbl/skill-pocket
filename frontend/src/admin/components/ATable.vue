<script setup>
import { useMobile } from '../composables/useMobile'
import ACheckbox from './ACheckbox.vue'

// 数据表格：≥ sm 是表格，手机上自动变成卡片。每列用 mobile 指定卡片里的位置：
//   'title' 标题行（放头像 / 名称）/ 'sub' 标题下的小字 / 'meta' 底部一排小字（mlabel: true 时带上列名）/ 'action' 右上角操作 / 'hide' 手机上不显示
//   columns：[{ key, label, align?: 'right', mobile?, mlabel?, hideBelow?: 'md' | 'lg', class? }]
//   单元格内容用插槽 #cell-<key>="{ row, value }" 自定义；传 selection（useSelection 的返回值）会多出勾选列
const props = defineProps({
  columns: { type: Array, required: true },
  rows: { type: Array, default: () => [] },
  rowKey: { type: String, default: 'id' },
  selection: { type: Object, default: null },
  loading: Boolean,
  clickable: Boolean,
  emptyText: { type: String, default: '没有符合条件的记录' },
})
const emit = defineEmits(['row-click'])
const mobile = useMobile()
const HIDE = { md: 'hidden md:table-cell', lg: 'hidden lg:table-cell' }
const by = (role) => props.columns.filter((c) => (c.mobile || 'meta') === role)
const title = () => by('title')[0]
const sub = () => by('sub')[0]
const checked = (r) => props.selection?.has(r[props.rowKey])
const canPick = (r) => !props.selection || props.selection.selectable(r)
const pageValue = () => (props.selection.pageState === 'all' ? true : props.selection.pageState === 'some' ? 'mixed' : false)
</script>

<template>
  <div v-if="loading && !rows.length" class="p-3.5"><div class="skeleton h-60" /></div>
  <div v-else-if="!rows.length"><slot name="empty"><p class="empty">{{ emptyText }}</p></slot></div>

  <!-- 手机：卡片 -->
  <ul v-else-if="mobile" class="m-0 list-none p-0">
    <li
      v-for="r in rows"
      :key="r[rowKey]"
      class="flex gap-3 border-b border-line px-4 py-3 last:border-0"
      :class="[checked(r) ? 'bg-primary-soft/50' : '', clickable ? 'cursor-pointer active:bg-subtle' : '']"
      @click="emit('row-click', r)"
    >
      <ACheckbox v-if="selection && canPick(r)" class="mt-1" :model-value="!!checked(r)" label="选择" @update:model-value="selection.toggle(r[rowKey])" />
      <span v-else-if="selection" class="w-[18px] shrink-0" />
      <div class="min-w-0 flex-1">
        <div class="flex items-start gap-2">
          <div class="min-w-0 flex-1">
            <slot v-if="title()" :name="`cell-${title().key}`" :row="r" :value="r[title().key]">{{ r[title().key] }}</slot>
            <p v-if="sub()" class="m-0 truncate text-xs text-mute"><slot :name="`cell-${sub().key}`" :row="r" :value="r[sub().key]">{{ r[sub().key] }}</slot></p>
          </div>
          <div v-for="c in by('action')" :key="c.key" class="shrink-0" @click.stop><slot :name="`cell-${c.key}`" :row="r" :value="r[c.key]" /></div>
        </div>
        <div v-if="by('meta').length" class="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-2">
          <span v-for="c in by('meta')" :key="c.key" class="flex items-center gap-1" :class="c.mclass">
            <span v-if="c.mlabel" class="text-mute">{{ c.label }}</span>
            <slot :name="`cell-${c.key}`" :row="r" :value="r[c.key]">{{ r[c.key] }}</slot>
          </span>
        </div>
      </div>
    </li>
  </ul>

  <!-- 桌面：表格 -->
  <div v-else class="overflow-x-auto">
    <table class="tbl">
      <thead>
        <tr>
          <th v-if="selection" class="w-10 !pr-0"><ACheckbox :model-value="pageValue()" label="本页全选" @update:model-value="selection.togglePage()" /></th>
          <th v-for="c in columns" :key="c.key" :class="[c.align === 'right' ? 'text-right' : '', HIDE[c.hideBelow], c.class]">{{ c.label }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="r in rows" :key="r[rowKey]" :class="[checked(r) ? 'sel' : '', clickable ? 'cursor-pointer' : '']" @click="emit('row-click', r)">
          <td v-if="selection" class="!pr-0"><ACheckbox v-if="canPick(r)" :model-value="!!checked(r)" label="选择" @update:model-value="selection.toggle(r[rowKey])" /></td>
          <td v-for="c in columns" :key="c.key" :class="[c.align === 'right' ? 'text-right' : '', HIDE[c.hideBelow], c.class]">
            <slot :name="`cell-${c.key}`" :row="r" :value="r[c.key]">{{ r[c.key] }}</slot>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.tbl tbody tr.sel td { background: color-mix(in srgb, var(--color-primary-soft) 60%, white); }
</style>
