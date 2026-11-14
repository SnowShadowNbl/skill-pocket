<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { startVoice, voiceSupported } from '../composables/voice'
import { toast } from '../composables/toast'
import Icon from './Icon.vue'
import AiTag from './AiTag.vue'

const emit = defineEmits(['text'])

const enabled = ref(null) // null = 检查中
const state = ref('idle') // idle / starting / recording / finishing
const cancelZone = ref(false)
const text = ref('')
const level = ref(0)
let session = null
let startY = 0
let releasedEarly = false

const reason = computed(() => {
  if (!voiceSupported()) return '当前环境不支持录音（需要 HTTPS 访问）'
  if (enabled.value === false) return '语音识别服务未配置'
  return ''
})

onMounted(async () => {
  try {
    enabled.value = (await (await fetch('/api/meta')).json()).asr_enabled
  } catch {
    enabled.value = false
  }
})

async function begin(e) {
  if (reason.value || state.value !== 'idle') return
  e?.preventDefault()
  try {
    if (e?.pointerId != null) e.currentTarget.setPointerCapture(e.pointerId)
  } catch {}
  startY = e?.clientY ?? 0
  cancelZone.value = false
  releasedEarly = false
  text.value = ''
  level.value = 0
  state.value = 'starting'
  try {
    session = await startVoice({
      onText: (t) => (text.value = t),
      onLevel: (l) => (level.value = Math.min(1, l * 6)),
      onError: (m) => {
        toast(m, 'error')
        abort()
      },
    })
  } catch (err) {
    state.value = 'idle'
    toast(err?.name === 'NotAllowedError' ? '没有麦克风权限，请在浏览器设置里允许' : '无法开启麦克风', 'error')
    return
  }
  state.value = 'recording'
  navigator.vibrate?.(15)
  if (releasedEarly) end() // 权限弹窗期间就松手了
}

function move(e) {
  if (state.value !== 'recording') return
  cancelZone.value = startY - e.clientY > 70
}

async function end() {
  if (state.value === 'starting') {
    releasedEarly = true
    return
  }
  if (state.value !== 'recording') return
  if (cancelZone.value) return abort()
  state.value = 'finishing'
  const result = await session.stop()
  session = null
  state.value = 'idle'
  if (result) {
    emit('text', result)
    toast('已转成文字，可以修改后再发送', 'success', 2200)
  } else {
    toast('没有识别到内容', 'info', 1800)
  }
}

function abort() {
  session?.cancel()
  session = null
  state.value = 'idle'
  cancelZone.value = false
}

// 键盘：按住空格说话
function keydown(e) {
  if (e.code === 'Space' && !e.repeat) begin(e)
}
function keyup(e) {
  if (e.code === 'Space') end()
}

onBeforeUnmount(abort)
</script>

<template>
  <button
    type="button"
    class="btn-glass touch-none select-none"
    :class="state === 'recording' ? 'bg-brand-soft text-brand' : ''"
    :disabled="!!reason || enabled === null"
    :title="reason || '按住说话，松开转成文字（上滑取消）'"
    :aria-label="reason || '按住说话'"
    @pointerdown="begin"
    @pointermove="move"
    @pointerup="end"
    @pointercancel="abort"
    @keydown="keydown"
    @keyup="keyup"
    @contextmenu.prevent
  >
    <Icon name="mic" :size="17" />{{ state === 'idle' ? '按住说话' : state === 'starting' ? '准备中…' : state === 'finishing' ? '识别中…' : '松开结束' }}
  </button>

  <Teleport to="body">
    <Transition name="toast">
      <div
        v-if="state === 'recording' || state === 'finishing'"
        class="pointer-events-none fixed inset-x-4 bottom-[calc(96px+env(safe-area-inset-bottom))] z-[80] mx-auto max-w-md"
        role="status"
        aria-live="polite"
      >
        <div
          class="glass-strong rounded-[12px] p-5 text-center shadow-[0_24px_60px_-20px_rgb(11_47_122/0.55)] transition-colors duration-300"
          :class="cancelZone ? 'bg-danger-soft' : ''"
        >
          <div class="relative mx-auto grid h-20 w-20 place-items-center">
            <span
              class="absolute inset-0 rounded-full transition-transform duration-100"
              :class="cancelZone ? 'bg-danger/20' : 'bg-linear-135 from-brand/25 to-brand-2/25'"
              :style="{ transform: `scale(${1 + level * 0.6})` }"
            />
            <span
              class="relative grid h-14 w-14 place-items-center rounded-full text-white"
              :class="cancelZone ? 'bg-danger' : 'bg-brand'"
            >
              <Icon :name="cancelZone ? 'x' : state === 'finishing' ? 'sparkles' : 'mic'" :size="26" :class="state === 'finishing' ? 'animate-pulse' : ''" />
            </span>
          </div>
          <p class="mt-3 min-h-[3em] text-[15px] leading-relaxed text-ink">
            {{ text || (state === 'finishing' ? '正在整理识别结果…' : '正在聆听，请说话…') }}
          </p>
          <p class="mt-2 text-xs" :class="cancelZone ? 'font-semibold text-danger' : 'text-mute'">
            {{ cancelZone ? '松开手指，取消这段语音' : state === 'finishing' ? '马上就好' : '松开结束 · 上滑取消' }}
          </p>
          <AiTag asr class="mt-2" />
        </div>
      </div>
    </Transition>
  </Teleport>
</template>
