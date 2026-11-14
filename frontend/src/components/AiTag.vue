<script setup>
import { computed } from 'vue'
import { meta, loadMeta } from '../composables/meta'

// 用到 AI 的地方统一显示「✨ 模型名」；不传 model 时显示当前配置的文本模型
const props = defineProps({ model: { type: String, default: '' }, asr: Boolean })
loadMeta()
const label = computed(() => props.model || (props.asr ? meta.data?.asr_model : meta.data?.ai_model) || '')
</script>

<template>
  <span v-if="label" class="ai-tag" :title="`由 ${label} 生成`">
    <b>AI</b><span class="lbl">{{ label }}</span>
  </span>
</template>

<style scoped>
.ai-tag {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  height: 20px;
  padding: 0 7px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.01em;
  white-space: nowrap;
  max-width: 100%;
  color: var(--color-brand);
  background: linear-gradient(135deg, rgb(30 86 214 / 0.1), rgb(30 86 214 / 0.1));
  border: 1px solid rgb(30 86 214 / 0.18);
}
.ai-tag b {
  padding: 0 4px;
  margin-left: -4px;
  border-radius: 999px;
  font-size: 10px;
  font-weight: 800;
  color: #fff;
  background: linear-gradient(135deg, var(--color-brand), var(--color-brand-2));
}
</style>

<style scoped>
/* v3.2.1：窄卡片里模型名放不下时省略，不撑破布局 */
.ai-tag b {
  flex-shrink: 0;
}
.ai-tag .lbl {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
