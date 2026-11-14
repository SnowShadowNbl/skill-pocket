<script setup>
import CheckBox from '../../components/CheckBox.vue'

// 管理端勾选框：包一层主站的 CheckBox（支持半选 'mixed'），点击区加大到 40px
//   <ACheckbox :model-value="true | false | 'mixed'" label="…" @update:model-value="…" />
const props = defineProps({ modelValue: { type: [Boolean, String], default: false }, label: { type: String, default: '' }, disabled: Boolean })
const emit = defineEmits(['update:modelValue'])
const flip = () => !props.disabled && emit('update:modelValue', props.modelValue !== true)
</script>

<template>
  <span class="a-cb -m-[11px] grid h-10 w-10 shrink-0 cursor-pointer place-items-center" @click.stop="flip">
    <CheckBox :checked="modelValue" :label="label" :disabled="disabled" @toggle="flip" />
  </span>
</template>
