<script setup>
import { computed, ref, watch } from 'vue'
import { api, authHeaders } from '../../api'
import { confirmDialog } from '../../composables/dialog'
import { toast } from '../../composables/toast'
import Icon from '../../components/Icon.vue'

// v3.3.89 额度用完弹窗里给用户看的联系方式：微信号 + 名片二维码
const props = defineProps({ settings: Object })
const emit = defineEmits(['update'])
const wechat = ref('')
const busy = ref(false)
const fileInput = ref(null)
watch(() => props.settings?.contact?.wechat, (v) => (wechat.value = v || ''), { immediate: true })
const dirty = computed(() => wechat.value.trim() !== (props.settings?.contact?.wechat || ''))
const qr = computed(() => props.settings?.contact?.qr)

async function saveWechat() {
  busy.value = true
  try {
    emit('update', await api('/api/admin/quota/settings', { method: 'PUT', body: { contact_wechat: wechat.value.trim() } }))
    toast('已保存', 'success')
  } catch (e) {
    toast(e.message, 'error')
  } finally {
    busy.value = false
  }
}

async function upload(e) {
  const file = e.target.files?.[0]
  e.target.value = ''
  if (!file) return
  busy.value = true
  try {
    const fd = new FormData()
    fd.append('file', file)
    const res = await fetch('/api/admin/quota/contact-qr', { method: 'POST', body: fd, headers: authHeaders() })
    const data = await res.json().catch(() => ({}))
    if (!res.ok) throw new Error((typeof data.detail === 'string' && data.detail) || `上传失败（${res.status}）`)
    emit('update', data)
    toast('名片已更新', 'success')
  } catch (err) {
    toast(err.message, 'error')
  } finally {
    busy.value = false
  }
}

async function removeQr() {
  if (!(await confirmDialog({ title: '删除名片二维码？', okText: '删除', danger: true }))) return
  try {
    emit('update', await api('/api/admin/quota/contact-qr', { method: 'DELETE' }))
  } catch (e) {
    toast(e.message, 'error')
  }
}
</script>

<template>
  <section class="card">
    <div class="card-hd"><h2>额度用完时的联系方式</h2></div>
    <div v-if="!settings" class="card-bd"><div class="skeleton h-28" /></div>
    <div v-else class="card-bd grid gap-5 sm:grid-cols-[minmax(0,1fr)_auto]">
      <form class="flex flex-wrap items-end gap-2 self-start" @submit.prevent="saveWechat">
        <label class="min-w-0 flex-1 text-xs text-mute">管理员微信号
          <input v-model="wechat" class="input mt-1" maxlength="60" />
        </label>
        <button class="btn btn-primary" :disabled="!dirty || busy">保存</button>
      </form>
      <div class="flex items-center gap-3">
        <div class="grid h-[120px] w-[120px] place-items-center overflow-hidden rounded-lg border border-line bg-subtle">
          <img v-if="qr" :src="qr" alt="名片二维码" class="h-full w-full object-contain" />
          <Icon v-else name="image" :size="26" class="text-mute" />
        </div>
        <div class="flex flex-col gap-2">
          <button class="btn" :disabled="busy" @click="fileInput.click()"><Icon name="image" :size="15" />{{ qr ? '更换名片' : '上传名片' }}</button>
          <button v-if="qr" class="btn" :disabled="busy" @click="removeQr"><Icon name="trash" :size="15" />删除</button>
          <input ref="fileInput" type="file" accept="image/*" class="hidden" @change="upload" />
        </div>
      </div>
    </div>
  </section>
</template>
