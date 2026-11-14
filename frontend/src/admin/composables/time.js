// 北京时间显示：后端给的 ISO 时间 → 'YYYY-MM-DD HH:mm'（和 ADateTime 的取值一致）
const fmt = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })
export const toBj = (iso) => (iso ? fmt.format(new Date(iso)).replace(',', '') : '')
// ADateTime 的取值 → 接口要的 ISO 字符串（不带时区，后端按北京时间处理）
export const fromBj = (s) => (s ? s.replace(' ', 'T') : null)
// 现在起 N 天（对齐到半小时）
export function afterDays(n) {
  const d = new Date(Date.now() + n * 864e5)
  const s = toBj(d.toISOString())
  return `${s.slice(0, 14)}${Number(s.slice(14)) >= 30 ? '30' : '00'}`
}
