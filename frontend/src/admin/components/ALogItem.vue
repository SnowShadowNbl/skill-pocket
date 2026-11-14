<script setup>
import UserAvatar from '../../components/UserAvatar.vue'

// 一条操作日志的内容：操作人、摘要、对象、原因、修改前后、失败信息。操作日志页和用户详情的「管理记录」共用
//   <ALogItem :row="r" compact @filter-user="(id) => …" @filter-target="(id) => …" />
//   compact：不显示操作人和对象（在某个用户的详情里，这两项是已知的）
defineProps({ row: { type: Object, required: true }, compact: Boolean })
defineEmits(['filter-user', 'filter-target'])

// 修改前后的取值显示：状态等枚举翻成中文，空值显示 —
const VALUE = { active: '正常', disabled: '已停用', deleted: '已注销', merged: '已合并', true: '是', false: '否' }
const show = (v) => (v == null || v === '' ? '—' : VALUE[String(v)] || String(v))
const changes = (r) => {
  const keys = [...new Set([...Object.keys(r.before || {}), ...Object.keys(r.after || {})])]
  return keys.map((k) => ({ key: k, name: r.fields?.[k] || k, from: show(r.before?.[k]), to: show(r.after?.[k]) }))
}
</script>

<template>
  <div class="min-w-0 flex-1">
    <button v-if="!compact && row.user" class="mb-0.5 flex items-center gap-1.5 text-xs hover:text-primary" :title="`只看 ${row.user.nickname} 的操作`" @click="$emit('filter-user', row.user.id)">
      <UserAvatar :user="row.user" :size="16" />{{ row.user.label || row.user.nickname }}
    </button>
    <span class="break-words">{{ row.summary }}</span>
    <button v-if="!compact && row.target_type === 'user' && row.target_id" class="mt-0.5 flex items-center gap-1 text-xs text-primary hover:underline" @click="$emit('filter-target', row.target_id)">
      对象：{{ row.target_label || `#${row.target_id}` }}
    </button>
    <p v-if="row.reason" class="mt-1 mb-0 border-l-2 border-line pl-2 text-xs text-ink-2">原因：{{ row.reason }}</p>
    <ul v-if="changes(row).length" class="m-0 mt-1 flex list-none flex-col gap-0.5 p-0">
      <li v-for="c in changes(row)" :key="c.key" class="flex flex-wrap items-center gap-1.5 text-xs">
        <span class="tag tag-gray">{{ c.name }}</span><span class="text-mute">{{ c.from }}</span><span class="text-mute">→</span><b class="font-medium">{{ c.to }}</b>
      </li>
    </ul>
    <p v-if="row.result === 'failed' && row.message" class="mt-1 mb-0 text-xs text-bad">{{ row.message }}</p>
  </div>
</template>
