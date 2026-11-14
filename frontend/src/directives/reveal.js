// v-reveal="序号"：进入视口时淡入上浮（从模糊到清晰），序号用于错落延迟
const reduce = typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches

const io =
  typeof IntersectionObserver !== 'undefined'
    ? new IntersectionObserver(
        (entries) => {
          for (const e of entries) {
            if (!e.isIntersecting) continue
            e.target.classList.add('in')
            io.unobserve(e.target)
          }
        },
        { rootMargin: '0px 0px -30px 0px' },
      )
    : null

export const reveal = {
  mounted(el, { value = 0 }) {
    if (reduce || !io) return
    el.classList.add('reveal')
    el.style.transitionDelay = `${Math.min(value, 8) * 55}ms`
    // 入场结束后清掉延迟，避免影响悬停动效
    el.addEventListener('transitionend', () => (el.style.transitionDelay = ''), { once: true })
    io.observe(el)
  },
  unmounted(el) {
    io?.unobserve(el)
  },
}
