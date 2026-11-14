<script setup>
import { nextTick, ref, watch } from 'vue'
import { api } from '../api'
import { toast } from '../composables/toast'
import Icon from './Icon.vue'
import Seg from './Seg.vue'

// v3.3.48 原作者申请下架：选身份、写原因，提交后由管理员处理
const props = defineProps({ open: Boolean, item: { type: Object, default: null } })
const emit = defineEmits(['close', 'done'])

const RELATIONS = [['author', '原作者'], ['maintainer', '维护者'], ['other', '其他']]
const relation = ref('author')
const reason = ref('')
const contact = ref('')
const busy = ref(false)
const box = ref(null)

watch(() => props.open, async (v) => {
  if (!v) return
  relation.value = 'author'
  reason.value = ''
  contact.value = ''
  await nextTick()
  box.value?.focus()
})

async function submit() {
  if (reason.value.trim().length < 5 || busy.value) return
  busy.value = true
  try {
    const r = await api(`/api/items/${props.item.id}/takedown`, {
      method: 'POST', body: { relation: relation.value, reason: reason.value.trim(), contact: contact.value.trim() },
    })
    toast('已提交，处理结果会通过消息通知你', 'success')
    emit('done', r.request)
    emit('close')
  } catch (e) {
    toast(e.message || '提交失败', 'error')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <Teleport to="body">
    <Transition name="sheet">
      <div
        v-if="open"
        class="fixed inset-0 z-[80] grid place-items-end bg-ink/25 backdrop-blur-[4px] sm:place-items-center"
        role="dialog"
        aria-modal="true"
        aria-labelledby="td-title"
        @click.self="emit('close')"
        @keydown.esc="emit('close')"
      >
        <form
          class="sheet-panel glass-strong pb-safe w-full rounded-t-[14px] p-6 shadow-[0_-24px_60px_-24px_rgb(11_47_122/0.45)] sm:max-w-[440px] sm:rounded-[12px]"
          @submit.prevent="submit"
        >
          <div class="flex items-start gap-3">
            <span class="grid h-10 w-10 shrink-0 place-items-center rounded-2xl bg-brand-soft text-brand"><Icon name="alert" :size="19" /></span>
            <div class="min-w-0 flex-1 pt-1">
              <h2 id="td-title" class="text-[17px] font-bold">申请下架「{{ item?.name }}」</h2>
            </div>
          </div>
          <p class="field-label mt-4">你的身份</p>
          <Seg v-model="relation" :options="RELATIONS" variant="soft" label="你的身份" />
          <label for="td-reason" class="field-label mt-3">原因</label>
          <textarea
            id="td-reason"
            ref="box"
            v-model="reason"
            rows="4"
            maxlength="1000"
            class="field resize-y rounded-2xl"
            placeholder="例如：我是这个仓库的作者，不希望被收录"
          />
          <label for="td-contact" class="field-label mt-3">联系方式（选填）</label>
          <input id="td-contact" v-model="contact" class="field" maxlength="200" placeholder="邮箱或 GitHub 主页" />
          <div class="mt-6 grid grid-cols-2 gap-2 sm:flex sm:justify-end">
            <button type="button" class="btn-glass" @click="emit('close')">取消</button>
            <button type="submit" class="btn-primary" :disabled="reason.trim().length < 5 || busy">{{ busy ? '提交中…' : '提交申请' }}</button>
          </div>
        </form>
      </div>
    </Transition>
  </Teleport>
</template>
