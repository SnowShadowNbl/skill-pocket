import { ref, watch } from 'vue'

const reduce = typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches

/** 数字从当前值滚动到目标值（ease-out），用于统计数据 */
export function useCountUp(source, duration = 1100) {
  const shown = ref(0)
  let raf
  watch(
    source,
    (target) => {
      cancelAnimationFrame(raf)
      if (target == null) return
      if (reduce) return (shown.value = target)
      const from = shown.value
      const start = performance.now()
      const step = (now) => {
        const p = Math.min(1, (now - start) / duration)
        shown.value = Math.round(from + (target - from) * (1 - Math.pow(1 - p, 3)))
        if (p < 1) raf = requestAnimationFrame(step)
      }
      raf = requestAnimationFrame(step)
    },
    { immediate: true },
  )
  return shown
}
