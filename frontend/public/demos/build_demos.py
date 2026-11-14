"""生成 5 个风格 demo：共用页面结构 + 各自的外观与动效。运行：python build_demos.py"""

from pathlib import Path

HERE = Path(__file__).parent

BODY = """<header class="topbar"><div class="wrap topbar-in">
  <a class="logo"><span class="logo-mark"><i data-icon="puzzle" data-size="19"></i></span><span>SkillBase</span></a>
  <nav class="topnav"><a class="btn btn-ghost"><i data-icon="layers" data-size="17"></i>分类管理</a><a class="btn btn-primary"><i data-icon="plus" data-size="17"></i>加入条目</a></nav>
</div></header>
{before_hero}
<section class="hero wrap">
  <h1>{h1}</h1>
  <p>每天凌晨自动采集 GitHub 星标增速榜，附中文介绍与安装方法</p>
  <div class="search"><i data-icon="search" data-size="20"></i><input id="search" type="search" enterkeyhint="search" placeholder="搜索名称、功能描述、仓库" aria-label="搜索"></div>
  <div class="stats"><div><b data-count="128">0</b><span>收录条目</span></div><div><b data-count="46">0</b><span>细分类别</span></div><div><b data-count="12">0</b><span>今日新增</span></div></div>
</section>
<main class="wrap">
  <div id="chips" class="chips" role="tablist" aria-label="分类"></div>
  <div class="list-head"><span id="count"></span><div class="seg" role="group" aria-label="排序"><button class="active" data-sort="stars">按星标</button><button data-sort="new">最新收录</button></div></div>
  <div id="list" class="list"></div>
</main>
{after_main}
<nav class="tabbar" aria-label="主导航"><a class="active"><i data-icon="home" data-size="22"></i><span>首页</span></a><a><i data-icon="plus" data-size="22"></i><span>加入</span></a><a><i data-icon="layers" data-size="22"></i><span>分类</span></a></nav>
<div id="overlay" class="overlay"></div>
<aside id="sheet" class="sheet" role="dialog" aria-modal="true"></aside>
<div id="toast" class="toast" role="status"></div>
<a class="demo-switch" href="index.html">← 返回方案对比</a>"""

PAGE = """<!doctype html>
<html lang="zh-CN"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{title} · SkillBase</title>
<link rel="stylesheet" href="common.css">
<style>{css}</style>
</head><body class="{body_class}">
{body}
<script>{config}</script>
<script src="data.js"></script>
<script src="common.js"></script>
</body></html>
"""

# ------------------------------------------------------------------ A 柔和卡片
CSS_A = """
:root{--p:#4f46e5;--p2:#4338ca;--ink:#0f172a;--ink2:#475569;--mute:#64748b;--line:#e6e9f2;--bg:#f5f7fb;--ease:cubic-bezier(.2,.8,.2,1)}
body{background:var(--bg);color:var(--ink)}
.topbar{background:rgba(245,247,251,.82);backdrop-filter:saturate(1.6) blur(12px);-webkit-backdrop-filter:saturate(1.6) blur(12px);border-bottom:1px solid transparent;transition:border-color .25s}
.topbar.scrolled{border-color:var(--line)}
.logo-mark{border-radius:10px;background:var(--p);color:#fff;box-shadow:0 6px 16px -6px rgba(79,70,229,.6)}
.btn{border-radius:12px;transition:transform .15s var(--ease),background .2s,box-shadow .25s,border-color .2s,color .2s}
.btn:active{transform:scale(.97)}
.btn-primary{background:var(--p);color:#fff;box-shadow:0 8px 20px -10px rgba(79,70,229,.8)}
.btn-primary:hover{background:var(--p2);box-shadow:0 14px 28px -12px rgba(79,70,229,.9)}
.btn-ghost{color:var(--ink2);background:#fff;border:1px solid var(--line)}
.btn-ghost:hover{border-color:#cdd3e1;color:var(--ink)}
.hero h1{font-weight:800}.hero h1 em{font-style:normal;color:var(--p)}.hero p{color:var(--ink2)}
.search>svg{color:var(--mute)}
.search input{background:#fff;border:1px solid var(--line);border-radius:16px;box-shadow:0 1px 2px rgba(15,23,42,.04);transition:border-color .2s,box-shadow .25s}
.search input:focus{border-color:var(--p);box-shadow:0 0 0 4px rgba(79,70,229,.12)}
.stats>div{background:#fff;border-radius:14px;border:1px solid var(--line)}.stats span{color:var(--mute)}
.chip{border-radius:999px;background:#fff;border:1px solid var(--line);color:var(--ink2);transition:all .22s var(--ease)}
.chip:hover{border-color:#cdd3e1;transform:translateY(-1px)}
.chip svg{color:var(--c)}
.chip.active{background:var(--ink);color:#fff;border-color:var(--ink)}.chip.active svg{color:#fff}
.list-head{color:var(--mute)}
.seg{background:#eaedf5;border-radius:10px}
.seg::before{background:#fff;border-radius:8px;box-shadow:0 1px 3px rgba(15,23,42,.12);transition:transform .3s var(--ease),width .3s var(--ease)}
.seg button{color:var(--ink2);transition:color .2s}.seg button.active{color:var(--ink);font-weight:600}
.card{background:#fff;border-radius:18px;border:1px solid var(--line);box-shadow:0 1px 2px rgba(15,23,42,.04);opacity:0;transform:translateY(18px);transition:opacity .5s var(--ease),transform .5s var(--ease),box-shadow .3s,border-color .3s}
.card.in{opacity:1;transform:none}
.card.in:hover{transform:translateY(-5px);box-shadow:0 22px 44px -20px rgba(15,23,42,.28);border-color:transparent}
.card.in:active{transform:translateY(-1px) scale(.99)}
.card-cover{background:var(--cs);margin:8px 8px 0;border-radius:12px}
.card-icon{background:#fff;color:var(--c);border-radius:18px;box-shadow:0 10px 22px -12px var(--c);transition:transform .4s var(--ease)}
.card:hover .card-icon{transform:scale(1.1) rotate(-6deg)}
.card-rise{background:#fff;color:#15803d;border-radius:999px}
.stars{color:var(--ink2)}.stars svg{color:#f59e0b;fill:#f59e0b}
.card p{color:var(--ink2)}
.tag{border-radius:8px}.tag-cat{background:var(--cs);color:var(--c)}
.tag-src.auto{background:#ecfdf3;color:#15803d}.tag-src.manual{background:#fff7e6;color:#b45309}
.skeleton .card-cover,.skeleton .bar{background:linear-gradient(90deg,#eef1f6 25%,#f8f9fc 50%,#eef1f6 75%);background-size:200% 100%;animation:shimmer 1.2s infinite}
.skeleton .bar{border-radius:6px}
.tabbar{background:rgba(255,255,255,.92);backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);border-top:1px solid var(--line)}
.tabbar a{color:var(--mute);transition:color .2s}.tabbar a.active{color:var(--p)}
.tabbar a svg{transition:transform .25s var(--ease)}.tabbar a:active svg{transform:scale(.82)}
.overlay{background:rgba(15,23,42,.35);transition:opacity .35s}
.sheet{background:#fff;border-radius:22px 22px 0 0;box-shadow:0 -20px 50px -20px rgba(15,23,42,.3);transition:transform .5s var(--ease),visibility .5s}
@media(min-width:768px){.sheet{border-radius:22px 0 0 22px}}
.sheet-handle{background:#dfe3ec}
.sheet-icon{background:var(--cs);color:var(--c);border-radius:16px}
.sheet-close{border-radius:12px;color:var(--mute);transition:background .2s,transform .3s var(--ease)}.sheet-close:hover{background:#f1f3f8;transform:rotate(90deg)}
.tag-group{background:#f1f3f8;color:var(--ink2)}
.sheet-summary,.sheet-desc p{color:var(--ink2)}.sheet-meta{color:var(--mute)}.sheet-meta svg{color:#f59e0b}
.step-n{background:var(--p);color:#fff;border-radius:8px}
.code{background:#0f172a;border-radius:12px}.code code{color:#e2e8f0}
.copy{border-radius:8px;color:#cbd5e1;border:1px solid rgba(255,255,255,.16);transition:all .2s}.copy:hover{background:rgba(255,255,255,.08)}.copy.copied{color:#4ade80;border-color:#4ade80}
.composer textarea{border:1px solid var(--line);border-radius:14px;background:#fafbfd;transition:border-color .2s,box-shadow .2s,background .2s}
.composer textarea:focus{border-color:var(--p);box-shadow:0 0 0 4px rgba(79,70,229,.1);background:#fff}
.mic.recording{background:#fee2e2;color:#dc2626;border-color:#fecaca}.wave i{background:#dc2626}
.comments li{border-top:1px solid var(--line)}.comments time,.comments li.none{color:var(--mute)}
.toast{background:var(--ink);color:#fff;border-radius:12px;transition:all .3s var(--ease)}
.empty{color:var(--mute)}
"""

# ------------------------------------------------------------------ B 极光玻璃
CSS_B = """
:root{--p1:#6366f1;--p2:#ec4899;--ink:#1e1b4b;--ink2:#4b5563;--mute:#6b7280;--glass:rgba(255,255,255,.58);--edge:rgba(255,255,255,.85);--ease:cubic-bezier(.22,1,.36,1)}
body{background:#f5f6ff;color:var(--ink);min-height:100vh}
.aurora{position:fixed;inset:0;z-index:-1;overflow:hidden;pointer-events:none}
.aurora i{position:absolute;width:60vmax;height:60vmax;border-radius:50%;filter:blur(70px);opacity:.55;animation:drift 18s ease-in-out infinite alternate}
.aurora i:nth-child(1){background:#a5b4fc;left:-15vmax;top:-20vmax}
.aurora i:nth-child(2){background:#f9a8d4;right:-20vmax;top:5vmax;animation-duration:22s;animation-delay:-6s}
.aurora i:nth-child(3){background:#99f6e4;left:20vmax;bottom:-30vmax;animation-duration:26s;animation-delay:-12s}
@keyframes drift{0%{transform:translate(0,0) scale(1)}50%{transform:translate(6vmax,4vmax) scale(1.12)}100%{transform:translate(-4vmax,8vmax) scale(.95)}}
.glass,.topbar,.stats>div,.card,.chip,.seg,.tabbar,.search input{background:var(--glass);backdrop-filter:blur(18px) saturate(1.5);-webkit-backdrop-filter:blur(18px) saturate(1.5);border:1px solid var(--edge)}
.topbar{border-width:0 0 1px;background:rgba(255,255,255,.35);transition:background .3s}
.topbar.scrolled{background:rgba(255,255,255,.7)}
.logo-mark{border-radius:12px;color:#fff;background:linear-gradient(135deg,var(--p1),var(--p2))}
.btn{border-radius:14px;transition:transform .2s var(--ease),box-shadow .3s,background .3s}
.btn:active{transform:scale(.96)}
.btn-primary{color:#fff;background:linear-gradient(135deg,var(--p1),var(--p2));box-shadow:0 10px 24px -10px rgba(99,102,241,.7)}
.btn-primary::after{content:"";position:absolute;inset:0;background:linear-gradient(110deg,transparent 30%,rgba(255,255,255,.45) 50%,transparent 70%);transform:translateX(-120%);transition:transform .7s var(--ease)}
.btn-primary:hover::after{transform:translateX(120%)}
.btn-primary:hover{box-shadow:0 16px 32px -12px rgba(236,72,153,.6)}
.btn-ghost{background:rgba(255,255,255,.5);border:1px solid var(--edge);color:var(--ink)}
.btn-ghost:hover{background:rgba(255,255,255,.8)}
.hero h1{font-weight:800}
.hero h1 em{font-style:normal;background:linear-gradient(90deg,var(--p1),var(--p2),#14b8a6,var(--p1));background-size:300% 100%;-webkit-background-clip:text;background-clip:text;color:transparent;animation:flow 8s linear infinite}
@keyframes flow{to{background-position:300% 0}}
.hero p{color:var(--ink2)}
.search>svg{color:var(--mute)}
.search input{border-radius:18px;transition:box-shadow .3s,background .3s}
.search input:focus{background:rgba(255,255,255,.85);box-shadow:0 0 0 4px rgba(99,102,241,.18),0 12px 30px -14px rgba(99,102,241,.5)}
.stats>div{border-radius:16px}.stats b{background:linear-gradient(135deg,var(--p1),var(--p2));-webkit-background-clip:text;background-clip:text;color:transparent}.stats span{color:var(--mute)}
.chip{border-radius:999px;color:var(--ink2);transition:all .3s var(--ease)}
.chip:hover{background:rgba(255,255,255,.85);transform:translateY(-2px)}
.chip svg{color:var(--c)}
.chip.active{color:#fff;border-color:transparent;background:linear-gradient(135deg,var(--p1),var(--p2));box-shadow:0 8px 20px -10px rgba(99,102,241,.8)}.chip.active svg{color:#fff}
.list-head{color:var(--mute)}
.seg{border-radius:12px}
.seg::before{border-radius:9px;background:linear-gradient(135deg,var(--p1),var(--p2));transition:transform .45s var(--ease),width .45s var(--ease)}
.seg button{color:var(--ink2);transition:color .3s}.seg button.active{color:#fff;font-weight:600}
.card{border-radius:22px;box-shadow:0 10px 30px -18px rgba(76,81,191,.35);opacity:0;transform:translateY(24px) scale(.97);filter:blur(4px);transition:opacity .7s var(--ease),transform .7s var(--ease),filter .7s var(--ease),box-shadow .4s,background .4s}
.card.in{opacity:1;transform:none;filter:none}
.card.in:hover{transform:translateY(-6px);background:rgba(255,255,255,.78);box-shadow:0 24px 48px -20px rgba(99,102,241,.45)}
.card-cover{background:transparent}
.card-cover::before{content:"";position:absolute;width:120px;height:120px;border-radius:50%;background:var(--c);opacity:.18;filter:blur(24px);transition:transform .6s var(--ease),opacity .4s}
.card:hover .card-cover::before{transform:scale(1.4);opacity:.3}
.card-icon{position:relative;border-radius:20px;color:var(--c);background:rgba(255,255,255,.75);border:1px solid var(--edge);animation:float 4s ease-in-out infinite;animation-delay:calc(var(--i) * -.6s)}
@keyframes float{50%{transform:translateY(-6px)}}
.card-rise{border-radius:999px;color:#047857;background:rgba(255,255,255,.75)}
.stars{color:var(--ink2)}.stars svg{color:#f59e0b;fill:#f59e0b}
.card p{color:var(--ink2)}
.tag{border-radius:999px}.tag-cat{background:rgba(255,255,255,.7);color:var(--c);border:1px solid var(--edge)}
.tag-src.auto{background:rgba(16,185,129,.12);color:#047857}.tag-src.manual{background:rgba(245,158,11,.14);color:#b45309}
.skeleton .card-cover,.skeleton .bar{background:linear-gradient(90deg,rgba(255,255,255,.4) 25%,rgba(255,255,255,.9) 50%,rgba(255,255,255,.4) 75%);background-size:200% 100%;animation:shimmer 1.4s infinite}
.skeleton .bar{border-radius:8px}.skeleton{filter:none!important}
.tabbar{border-width:1px 0 0;background:rgba(255,255,255,.7)}
.tabbar a{color:var(--mute);transition:color .3s}.tabbar a.active{color:var(--p1)}
.overlay{background:rgba(30,27,75,.18);backdrop-filter:blur(4px);-webkit-backdrop-filter:blur(4px);transition:opacity .4s}
.sheet{background:rgba(255,255,255,.82);backdrop-filter:blur(28px) saturate(1.6);-webkit-backdrop-filter:blur(28px) saturate(1.6);border:1px solid var(--edge);border-radius:28px 28px 0 0;box-shadow:0 -24px 60px -24px rgba(76,81,191,.45);transition:transform .6s var(--ease),visibility .6s}
@media(min-width:768px){.sheet{border-radius:28px 0 0 28px}}
.sheet-handle{background:rgba(30,27,75,.15)}
.sheet-icon{border-radius:18px;color:#fff;background:linear-gradient(135deg,var(--c),var(--p2))}
.sheet-close{border-radius:14px;color:var(--mute);transition:background .3s,transform .4s var(--ease)}.sheet-close:hover{background:rgba(255,255,255,.9);transform:rotate(90deg)}
.tag-group{background:rgba(99,102,241,.1);color:var(--p1)}
.sheet-summary,.sheet-desc p{color:var(--ink2)}.sheet-meta{color:var(--mute)}.sheet-meta svg{color:#f59e0b}
.step-n{border-radius:10px;color:#fff;background:linear-gradient(135deg,var(--p1),var(--p2))}
.code{border-radius:14px;background:#1e1b4b}.code code{color:#e0e7ff}
.copy{border-radius:10px;color:#c7d2fe;border:1px solid rgba(255,255,255,.2);transition:all .25s}.copy:hover{background:rgba(255,255,255,.1)}.copy.copied{color:#6ee7b7;border-color:#6ee7b7}
.composer textarea{border-radius:16px;background:rgba(255,255,255,.6);border:1px solid var(--edge);transition:box-shadow .3s,background .3s}
.composer textarea:focus{background:#fff;box-shadow:0 0 0 4px rgba(99,102,241,.15)}
.mic.recording{background:linear-gradient(135deg,#f43f5e,var(--p2));color:#fff;box-shadow:0 0 0 0 rgba(244,63,94,.5);animation:pulse 1.4s infinite}
@keyframes pulse{70%{box-shadow:0 0 0 14px rgba(244,63,94,0)}100%{box-shadow:0 0 0 0 rgba(244,63,94,0)}}
.wave i{background:linear-gradient(var(--p1),var(--p2))}
.comments li{border-top:1px solid rgba(30,27,75,.08)}.comments time,.comments li.none{color:var(--mute)}
.toast{border-radius:14px;color:#fff;background:linear-gradient(135deg,var(--p1),var(--p2));transition:all .4s var(--ease)}
.empty{color:var(--mute)}
"""

# ------------------------------------------------------------------ C 便当网格
CSS_C = """
:root{--ink:#111111;--ink2:#4a4a4a;--mute:#737373;--bg:#f6f5f1;--line:#e7e5df;--hi:#ffd84d;--spring:cubic-bezier(.34,1.4,.64,1);--ease:cubic-bezier(.16,1,.3,1)}
body{background:var(--bg);color:var(--ink)}
.topbar{background:rgba(246,245,241,.86);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);transition:box-shadow .3s}
.topbar.scrolled{box-shadow:0 1px 0 var(--line)}
.logo-mark{border-radius:12px;background:var(--ink);color:var(--hi)}
.btn{border-radius:999px;transition:transform .35s var(--spring),background .2s,color .2s}
.btn:hover{transform:translateY(-2px)}.btn:active{transform:scale(.95)}
.btn-primary{background:var(--ink);color:#fff}.btn-primary:hover{background:#2b2b2b}
.btn-ghost{background:#fff;color:var(--ink);border:1px solid var(--line)}
.hero h1{font-weight:900;font-size:clamp(30px,6.4vw,56px);letter-spacing:-.03em}
.hero h1 em{font-style:normal;background:linear-gradient(transparent 58%,var(--hi) 58%);background-size:0 100%;background-repeat:no-repeat;animation:mark 1s .4s var(--ease) forwards}
@keyframes mark{to{background-size:100% 100%}}
.hero p{color:var(--ink2)}
.search>svg{color:var(--ink)}
.search input{background:#fff;border:2px solid var(--ink);border-radius:20px;transition:box-shadow .3s var(--ease),transform .3s var(--ease)}
.search input:focus{box-shadow:6px 6px 0 var(--hi);transform:translate(-2px,-2px)}
.stats{gap:10px}
.stats>div{border-radius:22px;background:#fff;transition:transform .4s var(--spring)}
.stats>div:first-child{background:var(--ink);color:#fff}.stats>div:first-child span{color:#bdbdbd}
.stats>div:nth-child(2){background:var(--hi)}
.stats>div:hover{transform:rotate(-2deg) scale(1.03)}
.stats b{font-size:28px;font-weight:900}.stats span{color:var(--ink2)}
.chip{border-radius:999px;background:#fff;color:var(--ink2);border:1px solid var(--line);transition:all .35s var(--spring)}
.chip:hover{transform:translateY(-2px)}
.chip svg{color:var(--c)}
.chip.active{background:var(--ink);color:#fff;border-color:var(--ink);transform:scale(1.04)}.chip.active svg{color:var(--hi)}
.list-head{color:var(--mute)}
.seg{background:#fff;border:1px solid var(--line);border-radius:999px}
.seg::before{border-radius:999px;background:var(--ink);transition:transform .45s var(--spring),width .45s var(--spring)}
.seg button{color:var(--ink2);transition:color .25s}.seg button.active{color:#fff;font-weight:700}
.list{grid-template-columns:repeat(2,1fr);gap:12px}
.card:first-child{grid-column:1/-1}
@media(min-width:640px){.list{grid-template-columns:repeat(3,1fr)}.card:first-child{grid-column:span 2;grid-row:span 2}}
@media(min-width:1024px){.list{grid-template-columns:repeat(4,1fr);gap:16px}.card:nth-child(7){grid-column:span 2}}
.card{border-radius:24px;background:var(--cs);opacity:0;transform:scale(.92) translateY(20px);transition:opacity .6s var(--ease),transform .7s var(--spring)}
.card.in{opacity:1;transform:none}
.card.in:hover{transform:scale(1.025)}
.card.in:active{transform:scale(.98)}
.card-cover{height:92px;background:transparent}
.card:first-child .card-cover{height:clamp(140px,22vw,260px)}
.card-icon{width:52px;height:52px;border-radius:16px;background:#fff;color:var(--c);transition:transform .5s var(--spring)}
.card:first-child .card-icon{width:clamp(80px,10vw,120px);height:clamp(80px,10vw,120px);border-radius:28px}
.card:first-child .card-icon svg{width:50%;height:50%}
.card:hover .card-icon{transform:rotate(-10deg) scale(1.12)}
.card-rise{background:var(--ink);color:var(--hi);border-radius:999px}
.card:first-child .card-rise::before{content:"本周上升最快 ";}
.card-body{padding:4px 16px 16px}
.card h3{font-weight:800}
.card:first-child h3{font-size:clamp(20px,2.6vw,30px);white-space:normal}
.stars{color:var(--ink2)}.stars svg{color:var(--ink);fill:var(--ink)}
.card p{color:var(--ink2)}
.card:first-child p{font-size:15px;-webkit-line-clamp:3}
@media(max-width:639px){.card:not(:first-child) p{display:none}.card:not(:first-child) .tag-src{display:none}.card:not(:first-child) .stars{display:none}}
.tag{border-radius:999px}.tag-cat{background:#fff;color:var(--c);font-weight:600}
.tag-src.auto,.tag-src.manual{background:rgba(255,255,255,.6);color:var(--ink2)}
.skeleton{background:#ebe9e3}
.skeleton .bar{border-radius:8px;background:linear-gradient(90deg,#e2e0d9 25%,#f2f1ec 50%,#e2e0d9 75%);background-size:200% 100%;animation:shimmer 1.2s infinite}
.tabbar{background:var(--ink);margin:0 12px 12px;border-radius:24px;bottom:env(safe-area-inset-bottom);height:62px;padding:0}
.tabbar a{color:#9a9a9a;transition:color .25s}.tabbar a.active{color:var(--hi)}
.tabbar a svg{transition:transform .4s var(--spring)}.tabbar a.active svg{transform:translateY(-2px) scale(1.1)}
.overlay{background:rgba(17,17,17,.4);transition:opacity .35s}
.sheet{background:var(--bg);border-radius:28px 28px 0 0;transition:transform .6s var(--spring),visibility .6s}
@media(min-width:768px){.sheet{border-radius:28px 0 0 28px}}
.sheet-handle{background:#cfccc4}
.sheet-icon{border-radius:18px;background:var(--cs);color:var(--c)}
.sheet-close{border-radius:999px;background:#fff;transition:transform .4s var(--spring)}.sheet-close:hover{transform:rotate(90deg) scale(1.1)}
.sheet h2{font-weight:900}
.tag-group{background:var(--ink);color:#fff}
.sheet-summary,.sheet-desc p{color:var(--ink2)}.sheet-meta{color:var(--mute)}
.sheet h4{font-weight:800}
.step-n{border-radius:999px;background:var(--hi);color:var(--ink)}
.code{border-radius:16px;background:var(--ink)}.code code{color:#f5f5f5}
.copy{border-radius:999px;color:var(--ink);background:var(--hi);font-weight:600;transition:transform .35s var(--spring)}.copy:active{transform:scale(.9)}.copy.copied{background:#86efac}
.composer textarea{background:#fff;border:2px solid var(--line);border-radius:18px;transition:border-color .2s}
.composer textarea:focus{border-color:var(--ink)}
.mic{border:1px solid var(--line)}.mic.recording{background:var(--hi);border-color:var(--ink)}.wave i{background:var(--ink)}
.comments li{border-top:1px dashed #d6d3cb}.comments time,.comments li.none{color:var(--mute)}
.toast{background:var(--ink);color:var(--hi);border-radius:999px;transition:all .45s var(--spring)}
.empty{color:var(--mute)}
"""

# ------------------------------------------------------------------ D Material You
CSS_D = """
:root{--p:#6750a4;--onp:#fff;--pc:#eaddff;--sc:#e8def8;--onsc:#1d192b;--surf:#fef7ff;--c1:#f7f2fa;--c2:#f3edf7;--c3:#ece6f0;--ink:#1d1b20;--ink2:#49454f;--outline:#79747e;--ol:#cac4d0;--emph:cubic-bezier(.2,0,0,1);--dec:cubic-bezier(.3,0,.8,.15)}
body{background:var(--surf);color:var(--ink)}
.topbar{background:var(--surf);transition:background .4s var(--emph)}
.topbar.scrolled{background:var(--c2)}
.logo-mark{border-radius:12px;background:var(--pc);color:#21005d}
.btn{border-radius:999px;font-weight:500;letter-spacing:.01em;transition:box-shadow .3s var(--emph),background .3s}
.btn-primary{background:var(--p);color:var(--onp)}.btn-primary:hover{box-shadow:0 1px 3px rgba(0,0,0,.2),0 2px 6px 2px rgba(0,0,0,.1)}
.btn-ghost{color:var(--p);border:1px solid var(--outline)}.btn-ghost:hover{background:rgba(103,80,164,.08)}
.hero h1{font-weight:400;letter-spacing:-.01em}.hero h1 em{font-style:normal;font-weight:600;color:var(--p)}
.hero p{color:var(--ink2)}
.search>svg{color:var(--ink2)}
.search input{background:var(--c3);border:0;border-radius:28px;transition:background .3s var(--emph),box-shadow .3s}
.search input:focus{background:var(--c2);box-shadow:inset 0 0 0 2px var(--p)}
.stats>div{background:var(--c1);border-radius:16px}.stats b{color:var(--p)}.stats span{color:var(--ink2)}
.chip{border-radius:8px;border:1px solid var(--outline);color:var(--ink2);transition:background .3s var(--emph),border-color .3s,padding .3s var(--emph)}
.chip:hover{background:rgba(73,69,79,.08)}
.chip svg{color:var(--ink2);transition:transform .35s var(--emph)}
.chip.active{background:var(--sc);color:var(--onsc);border-color:transparent}
.chip.active svg{transform:scale(1.15);color:var(--onsc)}
.list-head{color:var(--ink2)}
.seg{border:1px solid var(--outline);border-radius:999px;padding:0}
.seg::before{top:0;bottom:0;left:0;border-radius:999px;background:var(--sc);transition:transform .5s var(--emph),width .5s var(--emph)}
.seg button{height:38px;padding:0 16px;color:var(--ink);transition:color .3s}.seg button.active{color:var(--onsc);font-weight:600}
.card{border-radius:16px;background:var(--c1);opacity:0;transform:scale(.92);transform-origin:50% 0;transition:opacity .5s var(--emph),transform .6s var(--emph),background .3s,box-shadow .3s var(--emph)}
.card.in{opacity:1;transform:none}
.card::after{content:"";position:absolute;inset:0;background:var(--p);opacity:0;transition:opacity .2s;pointer-events:none}
.card.in:hover{box-shadow:0 1px 2px rgba(0,0,0,.3),0 1px 3px 1px rgba(0,0,0,.15)}
.card:hover::after{opacity:.06}.card:active::after{opacity:.1}
.card-cover{background:var(--cs);margin:0}
.card-icon{border-radius:50%;background:var(--surf);color:var(--c);transition:border-radius .5s var(--emph),transform .5s var(--emph)}
.card:hover .card-icon{border-radius:18px;transform:rotate(45deg)}
.card:hover .card-icon svg{transform:rotate(-45deg)}
.card-icon svg{transition:transform .5s var(--emph)}
.card-rise{border-radius:8px;background:var(--surf);color:#146c2e}
.stars{color:var(--ink2)}.stars svg{color:var(--p);fill:var(--p)}
.card p{color:var(--ink2)}
.tag{border-radius:8px}.tag-cat{background:var(--sc);color:var(--onsc)}
.tag-src.auto{background:#c4eed0;color:#0a3818}.tag-src.manual{background:#ffdbcb;color:#341100}
.skeleton .card-cover,.skeleton .bar{background:linear-gradient(90deg,var(--c3) 25%,var(--c1) 50%,var(--c3) 75%);background-size:200% 100%;animation:shimmer 1.3s infinite}
.skeleton .bar{border-radius:4px}
.tabbar{background:var(--c2);height:calc(80px + env(safe-area-inset-bottom))}
.tabbar a{color:var(--ink2);font-size:12px;font-weight:500;gap:4px}
.tabbar a svg{box-sizing:content-box;padding:4px 20px;border-radius:999px;transition:background .4s var(--emph),padding .4s var(--emph)}
.tabbar a.active{color:var(--ink)}.tabbar a.active svg{background:var(--sc);color:var(--onsc)}
.fab{position:fixed;right:16px;bottom:calc(96px + env(safe-area-inset-bottom));z-index:31;height:56px;padding:0 20px;border-radius:16px;background:var(--pc);color:#21005d;display:flex;align-items:center;gap:10px;font-weight:600;box-shadow:0 3px 6px rgba(0,0,0,.15),0 6px 14px rgba(0,0,0,.12);transition:padding .4s var(--emph),gap .4s var(--emph),transform .3s var(--emph);overflow:hidden}
.fab span{max-width:120px;white-space:nowrap;overflow:hidden;transition:max-width .4s var(--emph),opacity .3s}
.fab.shrink{padding:0 16px;gap:0}.fab.shrink span{max-width:0;opacity:0}
.fab:active{transform:scale(.95)}
@media(min-width:768px){.fab{bottom:28px;right:28px}}
.overlay{background:rgba(29,27,32,.32);transition:opacity .4s var(--emph)}
.sheet{background:var(--c1);border-radius:28px 28px 0 0;transition:transform .5s var(--emph),visibility .5s}
.sheet:not(.open){transition:transform .25s var(--dec),visibility .25s}
@media(min-width:768px){.sheet{border-radius:28px 0 0 28px}}
.sheet-handle{width:32px;height:4px;background:var(--outline);opacity:.4}
.sheet-icon{border-radius:16px;background:var(--cs);color:var(--c)}
.sheet-close{border-radius:999px;color:var(--ink2);transition:background .2s}.sheet-close:hover{background:rgba(73,69,79,.08)}
.sheet h2{font-weight:400;font-size:24px}
.tag-group{background:var(--c3);color:var(--ink2)}
.sheet-summary,.sheet-desc p{color:var(--ink2)}.sheet-meta{color:var(--ink2)}.sheet-meta svg{color:var(--p)}
.sheet h4{font-weight:500;color:var(--p)}
.step-n{border-radius:50%;background:var(--p);color:#fff}
.code{border-radius:12px;background:#322f35}.code code{color:#f5eff7}
.copy{border-radius:999px;color:#d0bcff;transition:background .2s}.copy:hover{background:rgba(208,188,255,.12)}.copy.copied{color:#b6f2c2}
.composer textarea{border:1px solid var(--outline);border-radius:4px 4px 0 0;border-width:0 0 1px;background:var(--c3);transition:border-color .2s,box-shadow .2s}
.composer textarea:focus{border-color:var(--p);box-shadow:inset 0 -1px 0 var(--p)}
.mic{border:1px solid var(--outline);color:var(--p)}.mic.recording{background:#ffd8e4;color:#8c1d18;border-color:transparent}.wave i{background:var(--p)}
.comments li{border-top:1px solid var(--ol)}.comments time,.comments li.none{color:var(--ink2)}
.toast{background:#322f35;color:#f5eff7;border-radius:4px;transition:all .4s var(--emph)}
.ripple{background:var(--p);opacity:.16}.btn-primary .ripple{background:#fff;opacity:.3}
.empty{color:var(--ink2)}
"""

# ------------------------------------------------------------------ E 弹性触感
CSS_E = """
:root{--p:#ff6b4a;--pd:#e04a2a;--t:#14b8a6;--td:#0e8f81;--ink:#1f2a44;--ink2:#56607a;--mute:#6b7590;--bg:#eef3ff;--shadow:80,100,180;--bounce:cubic-bezier(.34,1.56,.64,1)}
body{background:var(--bg);color:var(--ink)}
.topbar{background:rgba(238,243,255,.85);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px)}
.logo-mark{border-radius:12px;background:var(--p);color:#fff;box-shadow:0 4px 0 var(--pd);animation:wiggle 3s 1.2s ease-in-out infinite}
@keyframes wiggle{0%,90%,100%{transform:rotate(0)}93%{transform:rotate(-12deg)}96%{transform:rotate(10deg)}}
.btn{border-radius:16px;font-weight:700;transition:transform .35s var(--bounce),box-shadow .15s}
.btn:active{transform:translateY(4px)}
.btn-primary{background:var(--p);color:#fff;box-shadow:0 4px 0 var(--pd),0 10px 18px -8px rgba(255,107,74,.6)}
.btn-primary:active{box-shadow:0 0 0 var(--pd)}
.btn-primary:hover{transform:translateY(-2px)}
.btn-ghost{background:#fff;color:var(--ink);box-shadow:0 4px 0 #d5ddf2}.btn-ghost:active{box-shadow:0 0 0 #d5ddf2}
.hero h1{font-weight:900}.hero h1 em{font-style:normal;color:var(--p);display:inline-block;animation:boing 1s .3s var(--bounce) both}
@keyframes boing{from{transform:scale(.3) rotate(-8deg);opacity:0}}
.hero p{color:var(--ink2)}
.search>svg{color:var(--mute)}
.search input{background:#fff;border:0;border-radius:20px;box-shadow:inset 0 3px 6px rgba(var(--shadow),.12),0 2px 0 #fff;transition:box-shadow .3s}
.search input:focus{box-shadow:inset 0 3px 6px rgba(var(--shadow),.12),0 0 0 4px rgba(20,184,166,.3)}
.stats>div{background:#fff;border-radius:20px;box-shadow:0 6px 0 -1px rgba(var(--shadow),.1),0 14px 24px -14px rgba(var(--shadow),.35);transition:transform .4s var(--bounce)}
.stats>div:active{transform:scale(.94)}
.stats b{color:var(--p);font-weight:900}.stats span{color:var(--mute)}
.chip{border-radius:16px;background:#fff;color:var(--ink2);font-weight:600;box-shadow:0 3px 0 #d5ddf2;transition:transform .4s var(--bounce),background .2s,color .2s,box-shadow .15s}
.chip:active{transform:translateY(3px);box-shadow:0 0 0 #d5ddf2}
.chip svg{color:var(--c)}
.chip.active{background:var(--t);color:#fff;box-shadow:0 3px 0 var(--td);animation:jelly .5s var(--bounce)}.chip.active svg{color:#fff}
@keyframes jelly{30%{transform:scale(1.12,.9)}60%{transform:scale(.95,1.06)}}
.list-head{color:var(--mute)}
.seg{background:#dde5f7;border-radius:14px;box-shadow:inset 0 2px 4px rgba(var(--shadow),.15)}
.seg::before{border-radius:11px;background:#fff;box-shadow:0 3px 0 #cfd8ee;transition:transform .5s var(--bounce),width .5s var(--bounce)}
.seg button{color:var(--ink2);font-weight:600}.seg button.active{color:var(--ink)}
.card{background:#fff;border-radius:26px;box-shadow:0 8px 0 -2px rgba(var(--shadow),.1),0 18px 30px -16px rgba(var(--shadow),.35);opacity:0;transform:scale(.8) translateY(30px);transition:opacity .4s ease,transform .6s var(--bounce),box-shadow .2s}
.card.in{opacity:1;transform:none}
.card.in:hover{transform:translateY(-6px) rotate(-.6deg)}
.card.in:active{transform:translateY(4px) scale(.97);box-shadow:0 2px 0 -2px rgba(var(--shadow),.1),0 6px 14px -10px rgba(var(--shadow),.35)}
.card-cover{margin:10px 10px 0;border-radius:20px;background:var(--cs);box-shadow:inset 0 -4px 0 rgba(0,0,0,.04)}
.card-icon{border-radius:22px;background:var(--c);color:#fff;box-shadow:0 5px 0 rgba(0,0,0,.18),inset 0 3px 0 rgba(255,255,255,.35)}
.card:hover .card-icon{animation:wobble .7s var(--bounce)}
@keyframes wobble{20%{transform:rotate(-14deg) scale(1.1)}45%{transform:rotate(10deg) scale(1.12)}70%{transform:rotate(-4deg)}}
.card-rise{border-radius:999px;background:#fff;color:#0e8f81;box-shadow:0 2px 0 rgba(0,0,0,.06)}
.card h3{font-weight:800}
.stars{color:var(--ink2);font-weight:600}.stars svg{color:#fbbf24;fill:#fbbf24}
.card p{color:var(--ink2)}
.tag{border-radius:10px;font-weight:600}.tag-cat{background:var(--cs);color:var(--c)}
.tag-src.auto{background:#d7f7f2;color:#0e7c70}.tag-src.manual{background:#ffe6df;color:#c2410c}
.skeleton .card-cover,.skeleton .bar{background:linear-gradient(90deg,#e6ecfa 25%,#f5f8ff 50%,#e6ecfa 75%);background-size:200% 100%;animation:shimmer 1.1s infinite}
.skeleton .bar{border-radius:8px}.skeleton{transform:none!important}
.tabbar{background:#fff;margin:0 12px 12px;border-radius:24px;bottom:env(safe-area-inset-bottom);height:64px;padding:0;box-shadow:0 6px 0 -1px rgba(var(--shadow),.12),0 14px 30px -10px rgba(var(--shadow),.4)}
.tabbar a{color:var(--mute);font-weight:600}.tabbar a.active{color:var(--p)}
.tabbar a.active svg{animation:hop .6s var(--bounce)}
@keyframes hop{40%{transform:translateY(-6px) scale(1.15)}}
.overlay{background:rgba(31,42,68,.35);transition:opacity .3s}
.sheet{background:var(--bg);border-radius:30px 30px 0 0;transition:transform .55s var(--bounce),visibility .55s}
.sheet:not(.open){transition:transform .3s ease-in,visibility .3s}
@media(min-width:768px){.sheet{border-radius:30px 0 0 30px}}
.sheet-handle{background:#c8d2ea;width:48px;height:6px}
.sheet-icon{border-radius:18px;background:var(--c);color:#fff;box-shadow:0 5px 0 rgba(0,0,0,.18)}
.sheet-close{border-radius:14px;background:#fff;box-shadow:0 3px 0 #d5ddf2;transition:transform .35s var(--bounce)}.sheet-close:active{transform:translateY(3px)}
.sheet h2{font-weight:900}
.tag-group{background:#fff;color:var(--ink2)}
.sheet-summary,.sheet-desc p{color:var(--ink2)}.sheet-meta{color:var(--mute)}.sheet-meta svg{color:#fbbf24}
.sheet h4{font-weight:800}
.step-n{border-radius:10px;background:var(--t);color:#fff;box-shadow:0 3px 0 var(--td)}
.code{border-radius:16px;background:var(--ink)}.code code{color:#e6ecfa}
.copy{border-radius:10px;background:var(--p);color:#fff;font-weight:700;box-shadow:0 3px 0 var(--pd);transition:transform .3s var(--bounce),box-shadow .1s}
.copy:active{transform:translateY(3px);box-shadow:0 0 0 var(--pd)}.copy.copied{background:var(--t);box-shadow:0 3px 0 var(--td);animation:jelly .5s var(--bounce)}
.composer textarea{background:#fff;border:0;border-radius:18px;box-shadow:inset 0 3px 6px rgba(var(--shadow),.12)}
.composer textarea:focus{box-shadow:inset 0 3px 6px rgba(var(--shadow),.12),0 0 0 4px rgba(20,184,166,.3)}
.mic.recording{background:var(--p);color:#fff;box-shadow:0 0 0 var(--pd);transform:translateY(4px) scale(1.04)}.wave i{background:var(--p)}
.comments li{border-top:2px dotted #d5ddf2}.comments time,.comments li.none{color:var(--mute)}
.comments li.new{animation:boing .6s var(--bounce)}
.toast{background:var(--t);color:#fff;border-radius:16px;font-weight:700;box-shadow:0 4px 0 var(--td);transition:all .45s var(--bounce)}
.empty{color:var(--mute)}
"""

FAB = """<button class="fab" aria-label="加入条目"><i data-icon="plus" data-size="22"></i><span>加入条目</span></button>"""
FAB_JS = """window.DEMO={ripple:true,init(){const f=document.querySelector('.fab');let y=scrollY;addEventListener('scroll',()=>{f.classList.toggle('shrink',scrollY>y&&scrollY>80);y=scrollY},{passive:true})}}"""

DEMOS = [
    ("a.html", "柔和卡片", "发现好用的 <em>Skill</em> 与 AI 模型", CSS_A, "", "", "window.DEMO={}"),
    ("b.html", "极光玻璃", "发现好用的 <em>Skill 与 AI 模型</em>", CSS_B, '<div class="aurora" aria-hidden="true"><i></i><i></i><i></i></div>', "", "window.DEMO={}"),
    ("c.html", "便当网格", "发现好用的 <em>Skill</em><br>与 AI 模型", CSS_C, "", "", "window.DEMO={}"),
    ("d.html", "Material You", "发现好用的 <em>Skill</em> 与 AI 模型", CSS_D, "", FAB, FAB_JS),
    ("e.html", "弹性触感", "发现好用的 <em>Skill</em> 与 AI 模型", CSS_E, "", "", "window.DEMO={}"),
]

for fname, title, h1, css, before, after, config in DEMOS:
    body = BODY.replace("{before_hero}", before).replace("{after_main}", after).replace("{h1}", h1)
    html = PAGE.replace("{title}", title).replace("{css}", css).replace("{body_class}", fname[0]).replace("{body}", body).replace("{config}", config)
    (HERE / fname).write_text(html, encoding="utf-8")
    print("wrote", fname)
