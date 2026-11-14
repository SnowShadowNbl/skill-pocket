<script setup>
import { onMounted, ref, watch } from 'vue'
import { api, formatTime, isCancelled } from '../api'
import { authState } from '../composables/auth'
import { confirmDialog } from '../composables/dialog'
import { toast } from '../composables/toast'
import UserAvatar from './UserAvatar.vue'
import Icon from './Icon.vue'
import VoiceButton from './VoiceButton.vue'
import RatingStars from './RatingStars.vue'

const props = defineProps({ itemId: [String, Number] })
const emit = defineEmits(['changed', 'rated'])

const comments = ref([])
const draft = ref('')
const rating = ref(0) // v3.3 好用度（0 = 不打分）
const sending = ref(false)
const fromVoice = ref(false) // 本条内容来自语音转写

function onVoice(t) {
  draft.value = draft.value ? `${draft.value.trimEnd()}${t}` : t
  fromVoice.value = true
}

async function load() {
  comments.value = await api(`/api/items/${props.itemId}/comments`)
}

async function send() {
  const content = draft.value.trim()
  if (!content) return
  sending.value = true
  try {
    const c = await api(`/api/items/${props.itemId}/comments`, { method: 'POST', body: { content, input_type: fromVoice.value ? 'voice' : 'text', rating: rating.value || null } })
    comments.value.unshift(c)
    draft.value = ''
    fromVoice.value = false
    if (rating.value && c.status !== 'pending') emit('rated')
    rating.value = 0
    emit('changed', comments.value.length)
    // v3.3：AI 拿不准的评论先给管理员看，只有自己能看到
    if (c.status === 'pending') toast('已提交，审核通过后其他人才能看到', 'info', 3500)
    else toast('已发送', 'success', 1500)
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  } finally {
    sending.value = false
  }
}

async function remove(c) {
  if (!(await confirmDialog({ title: '删除这条使用日志？', message: c.content.slice(0, 80), danger: true, okText: '删除' }))) return
  try {
    await api(`/api/comments/${c.id}`, { method: 'DELETE' })
    comments.value = comments.value.filter((x) => x.id !== c.id)
    emit('changed', comments.value.length)
    toast('已删除', 'success')
  } catch (e) {
    if (!isCancelled(e)) toast(e.message, 'error')
  }
}

onMounted(load)
// 登录 / 退出后刷新「能否删除」
watch(() => authState.version, load)
</script>

<template>
  <div>
    <form @submit.prevent="send">
      <label for="comment" class="sr-only">使用感受</label>
      <textarea
        id="comment"
        v-model="draft"
        rows="3"
        class="field resize-y rounded-2xl"
        :placeholder="authState.user ? '记录使用感受：好不好用、踩了什么坑' : '登录后可以记录使用感受'"
        @keydown.ctrl.enter="send"
        @keydown.meta.enter="send"
      />
      <!-- v3.3 好用度：可选，1~5 星 -->
      <div v-if="authState.user" class="mt-2"><RatingStars v-model="rating" editable :size="20" /></div>
      <div class="mt-2 flex items-center gap-2">
        <VoiceButton @text="onVoice" />
        <span class="hidden text-xs text-mute sm:inline">Ctrl + Enter 发送</span>
        <button type="submit" class="btn-primary ml-auto" :disabled="!draft.trim() || sending"><Icon name="send" :size="16" />发送</button>
      </div>
    </form>

    <TransitionGroup tag="ul" name="list-fade" class="mt-4">
      <li v-for="c in comments" :key="c.id" class="border-t border-line py-3">
        <div class="flex items-center gap-2 text-xs text-mute">
          <UserAvatar :user="c.author" :size="22" />
          <span class="font-semibold text-ink-2">{{ c.author?.nickname }}</span>
          <span v-if="authState.user && c.author?.id === authState.user.id" class="tag bg-brand-soft text-brand">我</span>
          <span v-if="c.status === 'pending'" class="tag bg-warn-soft text-warn" title="审核通过后其他人才能看到"><Icon name="clock" :size="12" />审核中</span>
          <RatingStars v-if="c.rating" :model-value="c.rating" :size="12" />
          <time :datetime="c.created_at">{{ formatTime(c.created_at) }}</time>
          <span v-if="c.input_type === 'voice'" class="tag bg-brand-soft text-brand"><Icon name="mic" :size="12" />语音</span>
          <button
            v-if="c.can_delete"
            class="ml-auto inline-flex h-8 cursor-pointer items-center gap-1 rounded-lg px-2 transition-colors duration-200 hover:bg-danger-soft hover:text-danger"
            aria-label="删除评论"
            @click="remove(c)"
          ><Icon name="trash" :size="14" />删除</button>
        </div>
        <p class="mt-1 pl-[30px] text-[14.5px] leading-relaxed break-words whitespace-pre-wrap">{{ c.content }}</p>
      </li>
      <li v-if="!comments.length" key="none" class="border-t border-line py-6 text-center text-sm text-mute">还没有使用日志</li>
    </TransitionGroup>
  </div>
</template>
