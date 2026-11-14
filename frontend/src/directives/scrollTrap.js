// v3.3.28 v-scroll-trap：浮层里的滚动列表接管滑动，滑动焦点留在列表上，不带动后面的页面。
// overscroll-behavior 只在元素真的能滚时生效（内容短、滚不动时拦不住），所以这里自己判断：
// 只有这个元素确实还能往手指的方向滚时才放行，其余（滚不动、滚到头）一律 preventDefault。
function canScroll(el, dy) {
  if (el.scrollHeight <= el.clientHeight + 1) return false
  if (dy < 0) return el.scrollTop > 0
  return el.scrollTop + el.clientHeight < el.scrollHeight - 1
}

export const scrollTrap = {
  mounted(el) {
    let y = 0
    el._trap = {
      start: (e) => (y = e.touches[0]?.clientY ?? 0),
      move: (e) => {
        const ny = e.touches[0]?.clientY ?? y
        const dy = y - ny
        y = ny
        if (!canScroll(el, dy) && e.cancelable) e.preventDefault()
      },
      wheel: (e) => {
        if (!canScroll(el, e.deltaY) && e.cancelable) e.preventDefault()
      },
    }
    el.style.overscrollBehavior = 'contain'
    el.addEventListener('touchstart', el._trap.start, { passive: true })
    el.addEventListener('touchmove', el._trap.move, { passive: false })
    el.addEventListener('wheel', el._trap.wheel, { passive: false })
  },
  unmounted(el) {
    if (!el._trap) return
    el.removeEventListener('touchstart', el._trap.start)
    el.removeEventListener('touchmove', el._trap.move)
    el.removeEventListener('wheel', el._trap.wheel)
  },
}
