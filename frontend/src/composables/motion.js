// v3 通用动效：按下涟漪、主按钮磁吸、卡片 3D 倾斜。系统开启「减少动态效果」时全部不生效
export const reduceMotion = typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches
export const finePointer = typeof matchMedia !== 'undefined' && matchMedia('(hover: hover) and (pointer: fine)').matches

const RIPPLE_SEL = '.rp, .btn-primary, .btn-glass, .btn-ghost, .btn-danger'

// 所有按钮按下时从指针位置扩散一圈
export function installRipple(selector = RIPPLE_SEL) {
  if (reduceMotion || typeof document === 'undefined') return
  document.addEventListener('pointerdown', (e) => {
    const el = e.target.closest?.(selector)
    if (!el || el.disabled) return
    const r = el.getBoundingClientRect()
    const d = Math.max(r.width, r.height) * 2.2
    const s = document.createElement('span')
    s.className = 'ripple'
    s.style.cssText = `width:${d}px;height:${d}px;left:${e.clientX - r.left - d / 2}px;top:${e.clientY - r.top - d / 2}px`
    el.appendChild(s)
    s.addEventListener('animationend', () => s.remove())
  })
}

// v-magnet：主按钮跟着指针轻微偏移
export const magnet = {
  mounted(el) {
    if (reduceMotion || !finePointer) return
    el.addEventListener('pointermove', (e) => {
      const r = el.getBoundingClientRect()
      el.style.translate = `${(e.clientX - r.left - r.width / 2) * 0.18}px ${(e.clientY - r.top - r.height / 2) * 0.3}px`
    })
    el.addEventListener('pointerleave', () => (el.style.translate = ''))
  },
}

// v-tilt：卡片 3D 倾斜 + 跟随光斑（触屏不启用）
export const tilt = {
  mounted(el) {
    if (reduceMotion || !finePointer) return
    el.classList.add('tilt')
    el.addEventListener('pointermove', (e) => {
      const r = el.getBoundingClientRect()
      const x = (e.clientX - r.left) / r.width
      const y = (e.clientY - r.top) / r.height
      el.style.setProperty('--mx', `${x * 100}%`)
      el.style.setProperty('--my', `${y * 100}%`)
      el.style.setProperty('--ry', `${(x - 0.5) * 6}deg`)
      el.style.setProperty('--rx', `${(0.5 - y) * 6}deg`)
    })
    el.addEventListener('pointerleave', () => {
      el.style.setProperty('--rx', '0deg')
      el.style.setProperty('--ry', '0deg')
    })
  },
}

// 收藏时爱心周围爆开 8 个小点
export function burst(el) {
  if (reduceMotion || !el) return
  for (let k = 0; k < 8; k++) {
    const p = document.createElement('i')
    p.className = 'burst-dot'
    p.style.setProperty('--a', `${k * 45}deg`)
    el.appendChild(p)
    p.addEventListener('animationend', () => p.remove())
  }
}
