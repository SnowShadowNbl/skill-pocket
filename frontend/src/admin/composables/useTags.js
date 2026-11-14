import { ref } from 'vue'
import { api } from '../../api'

// 用户标签（全后台共用一份，管理标签后刷新）
export const tagState = ref({ loaded: false, colors: [], items: [] })
export const TAG_COLOR = {
  blue: 'tag-blue',
  green: 'tag-ok',
  orange: 'tag-warn',
  red: 'tag-bad',
  purple: '!bg-[#f1eafd] !text-[#6b3fc4]',
  gray: 'tag-gray',
}
export const TAG_DOT = { blue: 'bg-primary', green: 'bg-ok', orange: 'bg-warn', red: 'bg-bad', purple: 'bg-[#6b3fc4]', gray: 'bg-mute' }
export const COLOR_NAME = { blue: '蓝', green: '绿', orange: '橙', red: '红', purple: '紫', gray: '灰' }

export async function loadTags(force = false) {
  if (tagState.value.loaded && !force) return tagState.value
  const d = await api('/api/admin/tags')
  tagState.value = { loaded: true, colors: d.colors, items: d.items }
  return tagState.value
}
