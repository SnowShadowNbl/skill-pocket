// 5 个 demo 共用的交互逻辑：骨架屏、错落入场、分类切换、详情抽屉、复制反馈、按住说话、波纹
(function () {
  const ICONS = {
    search: '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
    star: '<path d="M11.525 2.295a.53.53 0 0 1 .95 0l2.31 4.679a2.123 2.123 0 0 0 1.595 1.16l5.166.756a.53.53 0 0 1 .294.904l-3.736 3.638a2.123 2.123 0 0 0-.611 1.878l.882 5.14a.53.53 0 0 1-.771.56l-4.618-2.428a2.122 2.122 0 0 0-1.973 0L6.396 21.01a.53.53 0 0 1-.77-.56l.881-5.139a2.122 2.122 0 0 0-.611-1.879L2.16 9.795a.53.53 0 0 1 .294-.906l5.165-.755a2.122 2.122 0 0 0 1.597-1.16z"/>',
    plus: '<path d="M5 12h14"/><path d="M12 5v14"/>',
    home: '<path d="M15 21v-8a1 1 0 0 0-1-1h-4a1 1 0 0 0-1 1v8"/><path d="M3 10a2 2 0 0 1 .709-1.528l7-5.999a2 2 0 0 1 2.582 0l7 5.999A2 2 0 0 1 21 10v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    layers: '<path d="M12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83Z"/><path d="m22 17.65-9.17 4.16a2 2 0 0 1-1.66 0L2 17.65"/><path d="m22 12.65-9.17 4.16a2 2 0 0 1-1.66 0L2 12.65"/>',
    puzzle: '<path d="M15.39 4.39a1 1 0 0 0 1.68-.474 2.5 2.5 0 1 1 3.014 3.015 1 1 0 0 0-.474 1.68l1.683 1.682a2.414 2.414 0 0 1 0 3.414L19.61 15.39a1 1 0 0 1-1.68-.474 2.5 2.5 0 1 0-3.014 3.015 1 1 0 0 1 .474 1.68l-1.683 1.682a2.414 2.414 0 0 1-3.414 0L8.61 19.61a1 1 0 0 0-1.68.474 2.5 2.5 0 1 1-3.014-3.015 1 1 0 0 0 .474-1.68l-1.683-1.682a2.414 2.414 0 0 1 0-3.414L4.39 8.61a1 1 0 0 1 1.68.474 2.5 2.5 0 1 0 3.014-3.015 1 1 0 0 1-.474-1.68l1.683-1.682a2.414 2.414 0 0 1 3.414 0z"/>',
    audio: '<path d="M2 10v3"/><path d="M6 6v11"/><path d="M10 3v18"/><path d="M14 8v7"/><path d="M18 5v13"/><path d="M22 10v3"/>',
    image: '<rect width="18" height="18" x="3" y="3" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21"/>',
    wrench: '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>',
    bot: '<path d="M12 8V4H8"/><rect width="16" height="12" x="4" y="8" rx="2"/><path d="M2 14h2"/><path d="M20 14h2"/><path d="M15 13v2"/><path d="M9 13v2"/>',
    package: '<path d="M11 21.73a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73z"/><path d="M12 22V12"/><path d="m3.3 7 7.703 4.734a2 2 0 0 0 2.004 0L20.7 7"/><path d="m7.5 4.27 9 5.15"/>',
    github: '<path d="M15 22v-4a4.8 4.8 0 0 0-1-3.5c3 0 6-2 6-5.5.08-1.25-.27-2.48-1-3.5.28-1.15.28-2.35 0-3.5 0 0-1 0-3 1.5-2.64-.5-5.36-.5-8 0C6 2 5 2 5 2c-.3 1.15-.3 2.35 0 3.5A5.403 5.403 0 0 0 4 9c0 3.5 3 5.5 6 5.5-.39.49-.68 1.05-.85 1.65-.17.6-.22 1.23-.15 1.85v4"/><path d="M9 18c-4.51 2-5-2-8-2"/>',
    x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
    copy: '<rect width="14" height="14" x="8" y="8" rx="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>',
    check: '<path d="M20 6 9 17l-5-5"/>',
    mic: '<path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><path d="M12 19v3"/>',
    send: '<path d="M14.536 21.686a.5.5 0 0 0 .937-.024l6.5-19a.496.496 0 0 0-.635-.635l-19 6.5a.5.5 0 0 0-.024.937l7.93 3.18a2 2 0 0 1 1.112 1.11z"/><path d="m21.854 2.147-10.94 10.939"/>',
    trend: '<path d="M16 7h6v6"/><path d="m22 7-8.5 8.5-5-5L2 17"/>',
    inbox: '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
    sparkles: '<path d="M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .963 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.581a.5.5 0 0 1 0 .964L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.963 0z"/>',
  }
  const icon = (n, s = 20) =>
    `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[n] || ''}</svg>`
  window.icon = icon

  const cfg = window.DEMO || {}
  const GROUPS = window.DEMO_GROUPS
  const ITEMS = window.DEMO_ITEMS
  const groupOf = (code) => GROUPS.find((g) => g.code === code)
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches
  const $ = (s, el = document) => el.querySelector(s)
  const fmt = (n) => (n >= 10000 ? (n / 1000).toFixed(n >= 100000 ? 0 : 1) + 'k' : n.toLocaleString())
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c])

  const state = { q: '', group: '', sort: 'stars' }
  const comments = { 1: [{ t: '2026-11-01 21:14', c: '合并十几份合同 PDF 一次搞定，表格提取偶尔会错位。' }] }

  // ---------- 渲染 ----------
  document.querySelectorAll('[data-icon]').forEach((el) => {
    el.outerHTML = icon(el.dataset.icon, +(el.dataset.size || 20))
  })

  function cardHTML(it, i) {
    const g = groupOf(it.group)
    if (cfg.card) return cfg.card(it, i, g, { icon, fmt, esc })
    return `<article class="card" tabindex="0" role="button" data-id="${it.id}" style="--i:${i};--c:${g.color};--cs:${g.soft}">
      <div class="card-cover"><span class="card-icon">${icon(g.icon, 30)}</span>
        <span class="card-rise">${icon('trend', 13)}+${it.delta}</span></div>
      <div class="card-body">
        <div class="card-top"><h3>${esc(it.name)}</h3><span class="stars">${icon('star', 14)}${fmt(it.stars)}</span></div>
        <p>${esc(it.summary)}</p>
        <div class="card-tags"><span class="tag tag-cat">${esc(it.cat)}</span>
          <span class="tag tag-src ${it.source}">${it.source === 'auto' ? '系统采集' : '手动上传'}</span></div>
      </div></article>`
  }

  function filtered() {
    const q = state.q.toLowerCase()
    let list = ITEMS.filter((it) => (!state.group || it.group === state.group) && (!q || (it.name + it.summary + it.cat).toLowerCase().includes(q)))
    list = list.slice().sort((a, b) => (state.sort === 'stars' ? b.stars - a.stars : b.id - a.id))
    return list
  }

  const listEl = $('#list')
  const io = new IntersectionObserver(
    (entries) => entries.forEach((e) => {
      if (e.isIntersecting) {
        e.target.classList.add('in')
        io.unobserve(e.target)
      }
    }),
    { rootMargin: '0px 0px -30px 0px' },
  )

  function render() {
    const list = filtered()
    $('#count').textContent = `共 ${list.length} 个条目`
    listEl.innerHTML = list.length
      ? list.map(cardHTML).join('')
      : `<div class="empty">${icon('inbox', 36)}<p>没有符合条件的条目</p></div>`
    listEl.querySelectorAll('.card').forEach((el, i) => {
      el.style.transitionDelay = reduce ? '0ms' : `${Math.min(i, 8) * 55}ms`
      io.observe(el)
      // 入场后清掉延迟，避免影响 hover
      el.addEventListener('transitionend', () => (el.style.transitionDelay = '0ms'), { once: true })
    })
  }

  function rerender() {
    if (reduce) return render()
    listEl.classList.add('switching')
    setTimeout(() => {
      render()
      listEl.classList.remove('switching')
    }, 180)
  }

  function skeleton() {
    listEl.innerHTML = Array.from({ length: 6 }, () =>
      `<div class="card skeleton in"><div class="card-cover"></div><div class="card-body"><span class="bar w60"></span><span class="bar w90"></span><span class="bar w40"></span></div></div>`).join('')
  }

  // ---------- 分类 ----------
  const chipsEl = $('#chips')
  chipsEl.innerHTML =
    `<button class="chip active" data-g="">全部 <em>${ITEMS.length}</em></button>` +
    GROUPS.map((g) => `<button class="chip" data-g="${g.code}" style="--c:${g.color};--cs:${g.soft}">${icon(g.icon, 16)}${g.name} <em>${ITEMS.filter((i) => i.group === g.code).length}</em></button>`).join('')
  chipsEl.addEventListener('click', (e) => {
    const b = e.target.closest('.chip')
    if (!b || b.classList.contains('active')) return
    chipsEl.querySelector('.active').classList.remove('active')
    b.classList.add('active')
    b.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', inline: 'center', block: 'nearest' })
    state.group = b.dataset.g
    rerender()
  })

  // ---------- 排序分段控件 ----------
  const seg = $('.seg')
  seg.addEventListener('click', (e) => {
    const b = e.target.closest('button')
    if (!b || b.classList.contains('active')) return
    seg.querySelector('.active').classList.remove('active')
    b.classList.add('active')
    seg.style.setProperty('--x', b.offsetLeft - 3 + 'px')
    seg.style.setProperty('--w', b.offsetWidth + 'px')
    state.sort = b.dataset.sort
    rerender()
  })
  requestAnimationFrame(() => {
    const a = seg.querySelector('.active')
    seg.style.setProperty('--x', a.offsetLeft - 3 + 'px')
    seg.style.setProperty('--w', a.offsetWidth + 'px')
  })

  // ---------- 搜索 ----------
  let t
  $('#search').addEventListener('input', (e) => {
    clearTimeout(t)
    t = setTimeout(() => {
      state.q = e.target.value.trim()
      rerender()
    }, 220)
  })

  // ---------- 数字滚动 ----------
  document.querySelectorAll('[data-count]').forEach((el) => {
    const target = +el.dataset.count
    if (reduce) return (el.textContent = target)
    const start = performance.now()
    const step = (now) => {
      const p = Math.min(1, (now - start) / 1100)
      el.textContent = Math.round(target * (1 - Math.pow(1 - p, 3)))
      if (p < 1) requestAnimationFrame(step)
    }
    requestAnimationFrame(step)
  })

  // ---------- toast ----------
  const toastEl = $('#toast')
  let tt
  function toast(msg) {
    toastEl.innerHTML = icon('check', 16) + msg
    toastEl.classList.add('show')
    clearTimeout(tt)
    tt = setTimeout(() => toastEl.classList.remove('show'), 1600)
  }

  // ---------- 详情抽屉 ----------
  const sheet = $('#sheet')
  const overlay = $('#overlay')
  let lastFocus

  function commentsHTML(id) {
    return (comments[id] || []).map((c, i) => `<li class="${c.fresh ? 'new' : ''}"><time>${c.t}</time>${esc(c.c)}</li>`).join('') ||
      '<li class="none">还没有使用日志，按住麦克风说两句吧</li>'
  }

  function openSheet(id) {
    const it = ITEMS.find((x) => x.id === +id)
    const g = groupOf(it.group)
    sheet.style.setProperty('--c', g.color)
    sheet.style.setProperty('--cs', g.soft)
    sheet.innerHTML = `<div class="sheet-handle"></div><div class="sheet-inner">
      <div class="sheet-head"><span class="sheet-icon">${icon(g.icon, 28)}</span>
        <div><h2 id="sheet-title">${esc(it.name)}</h2><div class="sheet-tags"><span class="tag tag-group">${g.name}</span><span class="tag tag-cat">${esc(it.cat)}</span></div></div>
        <button class="sheet-close" aria-label="关闭">${icon('x', 20)}</button></div>
      <p class="sheet-summary">${esc(it.summary)}</p>
      <div class="sheet-meta"><span>${icon('star', 14)}<b>${fmt(it.stars)}</b> 星标</span><span>${icon('trend', 14)}今日 +${it.delta}</span><span>${it.lang}</span><span>${it.license}</span></div>
      <a class="btn btn-primary btn-block" href="javascript:void 0">${icon('github', 18)}在 GitHub 打开</a>
      <h4>功能介绍</h4><div class="sheet-desc">${it.desc.split('\n\n').map((p) => `<p>${esc(p)}</p>`).join('')}</div>
      <h4>安装与使用</h4><ol class="steps">${it.steps.map((s, i) => `<li><span class="step-n">${i + 1}</span><div style="min-width:0;flex:1"><b>${esc(s.title)}</b>${
        s.cmd ? `<div class="code"><code>${esc(s.cmd)}</code><button class="copy" data-copy="${esc(s.cmd)}">${icon('copy', 13)}复制</button></div>` : ''}</div></li>`).join('')}</ol>
      <h4>使用日志</h4>
      <div class="composer"><textarea id="cm" placeholder="记录使用感受，或按住麦克风说话"></textarea>
        <div class="composer-row"><button class="btn btn-ghost mic" aria-label="按住说话">${icon('mic', 18)}<span>按住说话</span></button>
          <span class="wave"><i></i><i></i><i></i><i></i><i></i></span>
          <button class="btn btn-primary send">${icon('send', 16)}发送</button></div></div>
      <ul class="comments">${commentsHTML(it.id)}</ul></div>`
    sheet.setAttribute('aria-labelledby', 'sheet-title')
    sheet.dataset.id = it.id
    lastFocus = document.activeElement
    overlay.classList.add('open')
    sheet.classList.add('open')
    sheet.scrollTop = 0
    document.body.style.overflow = 'hidden'
    setTimeout(() => $('.sheet-close', sheet).focus({ preventScroll: true }), 50)
  }

  function closeSheet() {
    overlay.classList.remove('open')
    sheet.classList.remove('open')
    document.body.style.overflow = ''
    lastFocus?.focus({ preventScroll: true })
  }

  listEl.addEventListener('click', (e) => {
    const c = e.target.closest('.card[data-id]')
    if (c) openSheet(c.dataset.id)
  })
  listEl.addEventListener('keydown', (e) => {
    const c = e.target.closest('.card[data-id]')
    if (c && (e.key === 'Enter' || e.key === ' ')) {
      e.preventDefault()
      openSheet(c.dataset.id)
    }
  })
  overlay.addEventListener('click', closeSheet)
  document.addEventListener('keydown', (e) => e.key === 'Escape' && sheet.classList.contains('open') && closeSheet())

  sheet.addEventListener('click', async (e) => {
    if (e.target.closest('.sheet-close')) return closeSheet()
    const cp = e.target.closest('.copy')
    if (cp) {
      try { await navigator.clipboard.writeText(cp.dataset.copy) } catch {}
      cp.classList.add('copied')
      cp.innerHTML = icon('check', 13) + '已复制'
      toast('已复制到剪贴板')
      setTimeout(() => {
        cp.classList.remove('copied')
        cp.innerHTML = icon('copy', 13) + '复制'
      }, 1400)
      return
    }
    if (e.target.closest('.send')) {
      const ta = $('#cm', sheet)
      const v = ta.value.trim()
      if (!v) return ta.focus()
      const id = sheet.dataset.id
      const d = new Date()
      const p = (n) => String(n).padStart(2, '0');
      (comments[id] = comments[id] || []).forEach((c) => (c.fresh = false))
      comments[id].unshift({ t: `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`, c: v, fresh: true })
      $('.comments', sheet).innerHTML = commentsHTML(id)
      ta.value = ''
      toast('已发送')
    }
  })

  // ---------- 按住说话（模拟流式转写） ----------
  const PHRASE = '这个用起来挺顺手的，安装两分钟就跑通了，中文识别也很准。'
  let rec
  sheet.addEventListener('pointerdown', (e) => {
    const mic = e.target.closest('.mic')
    if (!mic) return
    e.preventDefault()
    mic.setPointerCapture(e.pointerId)
    mic.classList.add('recording')
    $('span', mic).textContent = '松开结束'
    const ta = $('#cm', sheet)
    const base = ta.value
    let n = 0
    rec = setInterval(() => {
      n = Math.min(PHRASE.length, n + 2)
      ta.value = base + PHRASE.slice(0, n)
    }, 120)
    const stop = () => {
      clearInterval(rec)
      mic.classList.remove('recording')
      $('span', mic).textContent = '按住说话'
      mic.removeEventListener('pointerup', stop)
      mic.removeEventListener('pointercancel', stop)
    }
    mic.addEventListener('pointerup', stop)
    mic.addEventListener('pointercancel', stop)
  })

  // ---------- 波纹（Material 风格 demo 开启） ----------
  if (cfg.ripple && !reduce) {
    document.addEventListener('pointerdown', (e) => {
      const el = e.target.closest('.btn, .chip, .card, .tabbar a')
      if (!el) return
      const r = el.getBoundingClientRect()
      const size = Math.max(r.width, r.height)
      const s = document.createElement('span')
      s.className = 'ripple'
      s.style.cssText = `width:${size}px;height:${size}px;left:${e.clientX - r.left - size / 2}px;top:${e.clientY - r.top - size / 2}px`
      el.appendChild(s)
      setTimeout(() => s.remove(), 650)
    })
  }

  // 嵌在对比页的手机框里时，隐藏“返回方案对比”
  if (window.self !== window.top) $('.demo-switch')?.remove()

  // ---------- 顶栏滚动状态 ----------
  const topbar = $('.topbar')
  addEventListener('scroll', () => topbar.classList.toggle('scrolled', scrollY > 8), { passive: true })

  // ---------- 启动：骨架屏 → 列表 ----------
  skeleton()
  setTimeout(render, reduce ? 0 : 750)
  cfg.init?.({ icon, state })
})()
