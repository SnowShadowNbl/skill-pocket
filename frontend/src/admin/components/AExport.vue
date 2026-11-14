<script setup>
import { computed, ref } from 'vue'
import { authHeaders } from '../../api'
import Icon from '../../components/Icon.vue'
import { hasCap } from '../composables/usePermissions'
import { askVerify } from '../composables/verify'
import { toast } from '../../composables/toast'
import ACheckbox from './ACheckbox.vue'

// 按当前筛选导出 CSV：先显示条数确认；需要 export 能力，带邮箱的选项需要 export_email 能力（接口会再校验，并要求二次验证）。
//   <AExport endpoint="/api/admin/users/export" :params="uParams" :count="uData?.total" email />
//   令牌在请求头里，不能用链接直接下载，所以先 fetch 再保存；文件名取响应头的 Content-Disposition
const props = defineProps({
  endpoint: { type: String, required: true },
  params: { type: Object, default: () => new URLSearchParams() }, // 和列表相同的筛选（URLSearchParams）
  count: { type: Number, default: null },
  email: Boolean, // 这个导出可以带邮箱
  label: { type: String, default: '导出' },
})
const open = ref(false)
const withEmail = ref(false)
const busy = ref(false)
const canEmail = computed(() => hasCap('export_email'))

function fileName(res) {
  const m = /filename\*=UTF-8''([^;]+)|filename="?([^";]+)"?/i.exec(res.headers.get('content-disposition') || '')
  return decodeURIComponent(m?.[1] || m?.[2] || 'export.csv')
}
async function run() {
  busy.value = true
  try {
    const p = new URLSearchParams(props.params)
    if (withEmail.value) p.set('with_email', '1')
    const get = (token) => fetch(`${props.endpoint}?${p}`, { headers: token ? { ...authHeaders(), 'X-Verify-Token': token } : authHeaders() })
    let res = await get()
    if (res.status === 403) {
      // 带邮箱的导出要二次验证：通过后带令牌重试一次
      const d = await res.clone().json().catch(() => null)
      if (d?.detail?.code === 'verify_required') {
        const token = await askVerify({ action: d.detail.action || 'export_email', title: '导出带邮箱的用户' })
        if (token == null) return
        res = await get(token)
      }
    }
    if (!res.ok) {
      const d = await res.json().catch(() => null)
      throw new Error(d?.detail?.message || (typeof d?.detail === 'string' ? d.detail : `导出失败（${res.status}）`))
    }
    const url = URL.createObjectURL(await res.blob())
    const a = Object.assign(document.createElement('a'), { href: url, download: fileName(res) })
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
    toast('已导出', 'success')
    open.value = false
  } catch (e) {
    toast(e.message, 'error')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <button v-if="hasCap('export')" type="button" class="btn" @click="open = true; withEmail = false"><Icon name="download" :size="14" />{{ label }}</button>
  <Transition name="fade">
    <div v-if="open" class="fixed inset-0 z-50 grid place-items-end bg-ink/35 sm:place-items-center sm:px-4" @click.self="open = false" @keydown.esc="open = false">
      <form class="card w-full rounded-b-none p-5 shadow-[0_20px_50px_-20px_rgba(15,29,51,.35)] sm:max-w-[400px] sm:rounded-b-lg sm:p-6" role="dialog" aria-modal="true" aria-label="导出 CSV" @submit.prevent="run">
        <h2 class="m-0 text-base font-semibold">导出 CSV</h2>
        <p class="mt-3 mb-0 text-[13px]">按当前筛选导出 <b class="tabular-nums">{{ count == null ? '未知' : count }}</b> 条</p>
        <label v-if="email && canEmail" class="mt-4 flex cursor-pointer items-center gap-2.5 text-[13px]">
          <ACheckbox v-model="withEmail" label="含邮箱" />含邮箱
        </label>
        <div class="mt-5 flex justify-end gap-2">
          <button type="button" class="btn" @click="open = false">取消</button>
          <button class="btn btn-primary" :disabled="busy || count === 0">{{ busy ? '导出中…' : '导出' }}</button>
        </div>
      </form>
    </div>
  </Transition>
</template>
