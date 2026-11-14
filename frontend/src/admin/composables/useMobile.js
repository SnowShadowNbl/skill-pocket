import { onBeforeUnmount, ref } from 'vue'

// 当前是不是手机宽度（< 640px，和 Tailwind 的 sm 一致）
export function useMobile() {
  const mq = window.matchMedia('(max-width: 639.98px)')
  const mobile = ref(mq.matches)
  const on = (e) => { mobile.value = e.matches }
  mq.addEventListener('change', on)
  onBeforeUnmount(() => mq.removeEventListener('change', on))
  return mobile
}
