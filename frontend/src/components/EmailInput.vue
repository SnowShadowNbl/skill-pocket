<script>
const USED_KEY = 'skillpocket.emailDomains'

function used() {
  try {
    return JSON.parse(localStorage.getItem(USED_KEY) || '[]')
  } catch {
    return []
  }
}

/** 登录成功后记住用过的后缀 */
export function rememberDomain(email) {
  const d = email.split('@')[1]
  if (!d) return
  try {
    localStorage.setItem(USED_KEY, JSON.stringify([d, ...used().filter((x) => x !== d)].slice(0, 5)))
  } catch {}
}
</script>

<script setup>
import { computed, ref } from 'vue'

// 邮箱输入：输入 @ 后弹出常用后缀，↑↓ 选择、回车 / Tab 补全；用过的后缀排在最前
const model = defineModel({ type: String, default: '' })
defineProps({ id: { type: String, default: 'email' }, autofocus: Boolean })
const emit = defineEmits(['enter'])

const DOMAINS = [
  'qq.com', '163.com', '126.com', 'foxmail.com', 'gmail.com', 'outlook.com', 'hotmail.com', 'icloud.com',
  'yeah.net', 'sina.com', 'sina.cn', 'sohu.com', 'aliyun.com', '139.com', '189.cn', 'wo.cn', 'tom.com', '21cn.com',
  '88.com', 'live.com', 'msn.com', 'me.com', 'yahoo.com', 'protonmail.com', 'proton.me',
]
const focused = ref(false)
const active = ref(0)

const suggestions = computed(() => {
  const v = model.value.trim()
  const at = v.indexOf('@')
  if (at < 1 || v.indexOf('@', at + 1) !== -1) return []
  const name = v.slice(0, at)
  const typed = v.slice(at + 1).toLowerCase()
  const all = [...new Set([...used(), ...DOMAINS])]
  const list = all.filter((d) => d.startsWith(typed) && d !== typed)
  return list.slice(0, 6).map((d) => `${name}@${d}`)
})
const open = computed(() => focused.value && suggestions.value.length > 0)

function pick(s) {
  model.value = s
  active.value = 0
}

function onKey(e) {
  if (!open.value) {
    if (e.key === 'Enter') emit('enter')
    return
  }
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    active.value = (active.value + 1) % suggestions.value.length
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    active.value = (active.value - 1 + suggestions.value.length) % suggestions.value.length
  } else if (e.key === 'Enter' || e.key === 'Tab') {
    e.preventDefault()
    pick(suggestions.value[active.value])
  } else if (e.key === 'Escape') {
    focused.value = false
  }
}
</script>

<template>
  <div class="relative">
    <input
      :id="id"
      v-model.trim="model"
      type="email"
      inputmode="email"
      autocomplete="email"
      autocapitalize="off"
      spellcheck="false"
      class="field h-12 text-[15px] sm:h-12"
      placeholder="你的邮箱，如 name@qq.com"
      role="combobox"
      :aria-expanded="open"
      :aria-controls="`${id}-list`"
      :autofocus="autofocus"
      @focus="focused = true"
      @blur="focused = false"
      @input="active = 0"
      @keydown="onKey"
    />
    <Transition name="drop">
      <ul
        v-if="open"
        :id="`${id}-list`"
        class="glass-strong absolute inset-x-0 top-full z-20 mt-1.5 overflow-hidden rounded-2xl p-1 shadow-[0_16px_36px_-14px_rgb(11_47_122/0.5)]"
        role="listbox"
      >
        <li
          v-for="(s, i) in suggestions"
          :key="s"
          role="option"
          :aria-selected="i === active"
          class="flex h-10 cursor-pointer items-center rounded-xl px-3 text-[14px] transition-colors"
          :class="i === active ? 'bg-brand-soft text-brand' : 'text-ink-2 hover:bg-white/70'"
          @mousedown.prevent="pick(s)"
          @mouseenter="active = i"
        >
          <span class="truncate">{{ s.split('@')[0] }}<b class="font-semibold">@{{ s.split('@')[1] }}</b></span>
        </li>
      </ul>
    </Transition>
  </div>
</template>

<style scoped>
.drop-enter-active,
.drop-leave-active {
  transition: opacity 0.18s ease, transform 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}
.drop-enter-from,
.drop-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
</style>
