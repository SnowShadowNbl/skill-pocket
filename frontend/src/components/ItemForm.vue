<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
import { loadMeta, meta } from '../composables/meta'
import AppSelect from './AppSelect.vue'
import Icon from './Icon.vue'

// form: { name, category_id, summary, description, install_steps: [{title, command, note}], homepage_url }
const form = defineModel({ type: Object, required: true })
defineProps({ locked: { type: Array, default: () => [] }, showHomepage: { type: Boolean, default: true } })

const tree = ref([])

// 两级分类 → 下拉选项（按大类分组）
const catOptions = computed(() => tree.value.flatMap((g) => g.children.map((c) => ({ value: c.id, label: c.name, group: `${g.icon || ''} ${g.name}`.trim() }))))

function addStep() {
  form.value.install_steps.push({ title: '', command: '', note: '' })
}
function removeStep(i) {
  form.value.install_steps.splice(i, 1)
}
function moveStep(i, d) {
  const s = form.value.install_steps
  const j = i + d
  if (j < 0 || j >= s.length) return
  ;[s[i], s[j]] = [s[j], s[i]]
}

onMounted(async () => {
  loadMeta()
  tree.value = await api('/api/categories')
})
</script>

<template>
  <div class="space-y-5">
    <div class="grid gap-5 sm:grid-cols-2">
      <div>
        <label for="f-name" class="field-label flex items-center gap-1">
          名称 <span class="text-danger">*</span>
          <Icon v-if="locked.includes('name')" name="lock" :size="13" class="text-warn" title="已人工修改" />
        </label>
        <input id="f-name" v-model="form.name" class="field" required maxlength="200" />
      </div>
      <div>
        <label class="field-label flex items-center gap-1">
          分类 <span class="text-danger">*</span>
          <Icon v-if="locked.includes('category_id')" name="lock" :size="13" class="text-warn" />
        </label>
        <AppSelect v-model="form.category_id" :options="catOptions" placeholder="请选择分类" label="分类" searchable />
      </div>
    </div>

    <fieldset>
      <legend class="field-label flex items-center gap-1">
        使用类型 <Icon v-if="locked.includes('kind')" name="lock" :size="13" class="text-warn" />
      </legend>
      <div class="flex flex-wrap gap-1.5">
        <label
          v-for="k in meta.data?.kinds || []"
          :key="k.key"
          class="flex h-9 cursor-pointer items-center gap-1 rounded-full border px-3 text-[13px] transition-colors"
          :class="form.kind === k.key ? 'border-brand bg-brand-soft font-medium text-brand' : 'border-edge bg-white/60 text-ink-2 hover:bg-white'"
          :title="k.desc"
        >
          <input v-model="form.kind" type="radio" name="f-kind" :value="k.key" class="sr-only" />{{ k.icon }} {{ k.name }}
        </label>
      </div>
    </fieldset>

    <div>
      <label for="f-summary" class="field-label flex items-center gap-1">
        一句话描述 <Icon v-if="locked.includes('summary')" name="lock" :size="13" class="text-warn" />
      </label>
      <input id="f-summary" v-model="form.summary" class="field" maxlength="500" />
      <p class="mt-1 text-xs text-mute">它是干嘛用的，40 字以内为佳</p>
    </div>

    <div>
      <label for="f-desc" class="field-label flex items-center gap-1">
        功能介绍 <Icon v-if="locked.includes('description')" name="lock" :size="13" class="text-warn" />
      </label>
      <textarea id="f-desc" v-model="form.description" rows="6" class="field" />
      <p class="mt-1 text-xs text-mute">段落之间空一行</p>
    </div>

    <div v-if="showHomepage">
      <label for="f-home" class="field-label">主页链接</label>
      <input id="f-home" v-model="form.homepage_url" class="field" type="url" placeholder="https://" />
      <p class="mt-1 text-xs text-mute">非 GitHub 资源可填</p>
    </div>

    <fieldset>
      <div class="mb-2 flex items-center">
        <legend class="field-label mb-0 flex items-center gap-1">
          安装与使用步骤 <Icon v-if="locked.includes('install_steps')" name="lock" :size="13" class="text-warn" />
        </legend>
        <button type="button" class="btn-ghost btn-sm ml-auto text-brand" @click="addStep"><Icon name="plus" :size="15" />添加步骤</button>
      </div>
      <div class="space-y-3">
        <div v-for="(s, i) in form.install_steps" :key="i" class="rounded-2xl border border-line bg-white/50 p-3">
          <div class="flex items-center gap-1.5">
            <span class="grid h-6 w-6 shrink-0 place-items-center rounded-2xl bg-brand text-xs font-semibold text-white">{{ i + 1 }}</span>
            <input v-model="s.title" class="field h-10 sm:h-9" :aria-label="`第 ${i + 1} 步说明`" placeholder="步骤说明" />
            <button type="button" class="btn-ghost h-10 w-10 shrink-0 px-0 sm:h-9 sm:w-9" aria-label="上移" @click="moveStep(i, -1)"><Icon name="chevron-up" :size="16" /></button>
            <button type="button" class="btn-ghost h-10 w-10 shrink-0 px-0 sm:h-9 sm:w-9" aria-label="下移" @click="moveStep(i, 1)"><Icon name="chevron-down" :size="16" /></button>
            <button type="button" class="btn-ghost h-10 w-10 shrink-0 px-0 text-danger sm:h-9 sm:w-9" aria-label="删除此步" @click="removeStep(i)"><Icon name="x" :size="16" /></button>
          </div>
          <textarea v-model="s.command" rows="2" class="field mt-2 font-mono text-[13px]" :aria-label="`第 ${i + 1} 步命令`" placeholder="命令（可空）" />
          <input v-model="s.note" class="field mt-2 h-10 sm:h-9" :aria-label="`第 ${i + 1} 步补充说明`" placeholder="补充说明（可空）" />
        </div>
        <p v-if="!form.install_steps.length" class="text-sm text-mute">暂无步骤</p>
      </div>
    </fieldset>
  </div>
</template>
