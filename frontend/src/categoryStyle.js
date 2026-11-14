// 大类 → 图标与配色。v3.0 蓝白主题：只在蓝色系里做深浅区分（与后端 services/cover.py 的 GROUP_COLORS 一致）
const BG = '#eaf1fe'
const GROUPS = {
  coding: { icon: 'code', fg: '#1e56d6', bg: BG },
  office: { icon: 'file-text', fg: '#2f6bf0', bg: BG },
  writing: { icon: 'pencil', fg: '#2b6cb0', bg: BG },
  image: { icon: 'image', fg: '#3a7bea', bg: BG },
  video: { icon: 'play', fg: '#1e56d6', bg: BG },
  audio: { icon: 'audio', fg: '#2f6bf0', bg: BG },
  vision: { icon: 'eye', fg: '#0b6e8c', bg: BG },
  language: { icon: 'message', fg: '#3446b8', bg: BG },
  agent: { icon: 'bot', fg: '#1e56d6', bg: BG },
  research: { icon: 'search', fg: '#2b6cb0', bg: BG },
  infra: { icon: 'cpu', fg: '#3e516b', bg: '#f4f7fa' },
  ecosystem: { icon: 'puzzle', fg: '#0b2f7a', bg: BG },
}
const FALLBACK = { icon: 'folder', fg: '#3e516b', bg: '#f4f7fa' }

export function groupStyle(groupCode) {
  return GROUPS[groupCode] || FALLBACK
}

// 使用类型的配色（细边框小标签）
const KINDS = {
  agent_skill: { icon: 'puzzle', cls: 'border-[#c5d6f6] bg-[#f1f6ff] text-[#1e56d6]' },
  model: { icon: 'cpu', cls: 'border-[#cdd3f2] bg-[#f3f5ff] text-[#3446b8]' },
  app: { icon: 'wrench', cls: 'border-[#bfe1ec] bg-[#eff9fc] text-[#0b6e8c]' },
  dev: { icon: 'package', cls: 'border-[#d3dce8] bg-[#f4f7fa] text-[#3e516b]' },
  demo: { icon: 'flask', cls: 'border-[#c9ddf2] bg-[#f2f8fe] text-[#2b6cb0]' },
}

export function kindStyle(key) {
  return KINDS[key] || { icon: 'folder', cls: 'border-line bg-[#f4f7fa] text-ink-2' }
}
