<script setup>
import { useItemLink } from '../composables/itemLink'
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, isCancelled } from '../api'
import { toast } from '../composables/toast'
import Icon from './Icon.vue'
import ItemForm from './ItemForm.vue'

// 手动填写不在 GitHub 上的资源（原「新增 Skill → 搜索添加 → 手动填写」），可带预填内容
const itemLink = useItemLink()
const router = useRouter()
const emit = defineEmits(['back'])
const EMPTY = { name: '', category_id: null, kind: '', summary: '', description: '', homepage_url: '', install_steps: [] }
const form = ref({ ...EMPTY })
const creating = ref(false)

function fill(prefill = {}) {
  form.value = { ...EMPTY, ...prefill }
}

async function submit() {
  creating.value = true
  try {
    const body = {
      ...form.value,
      install_steps: form.value.install_steps
        .filter((s) => s.title.trim())
        .map((s) => ({ title: s.title.trim(), command: s.command?.trim() || null, note: s.note?.trim() || null })),
    }
    const r = await api('/api/items', { method: 'POST', body })
    toast('已加入', 'success')
    router.push(itemLink(r.id))
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  } finally {
    creating.value = false
  }
}

defineExpose({ fill })
</script>

<template>
  <form class="panel p-4 sm:p-6" @submit.prevent="submit">
    <div class="mb-5 flex items-center gap-2">
      <button type="button" class="btn-ghost btn-sm -ml-2" @click="emit('back')"><Icon name="arrow-left" :size="15" />返回</button>
      <span class="cap">手动填写</span>
    </div>
    <ItemForm v-model="form" />
    <div class="mt-6 flex justify-end border-t border-line-2 pt-5">
      <button type="submit" class="btn-primary w-full sm:w-auto" :disabled="creating || !form.name || !form.category_id">
        {{ creating ? '保存中…' : '加入' }}
      </button>
    </div>
  </form>
</template>
