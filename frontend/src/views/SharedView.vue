<script setup>
import { ref, watch } from 'vue'
import { RouterLink, RouterView } from 'vue-router'
import { api } from '../api'
import Icon from '../components/Icon.vue'
import ItemCard from '../components/ItemCard.vue'
import UserAvatar from '../components/UserAvatar.vue'

// v3.3 公开分享的收藏分类（只读，不需要登录）：/s/<token>
const props = defineProps({ token: { type: String, required: true } })
const data = ref(null)
const error = ref('')

watch(
  () => props.token,
  async (t) => {
    data.value = null
    error.value = ''
    try {
      data.value = await api(`/api/shared/${t}`)
      document.title = `${data.value.folder.name} · ${data.value.owner?.nickname || ''}的 Skill 口袋`
    } catch (e) {
      error.value = e.message
    }
  },
  { immediate: true },
)
</script>

<template>
  <div>
    <div v-if="error" class="panel mx-auto mt-8 flex max-w-md flex-col items-center gap-3 px-6 py-14 text-center">
      <span class="grid h-14 w-14 place-items-center rounded-2xl bg-brand-soft text-brand"><Icon name="lock" :size="24" /></span>
      <p class="font-semibold">{{ error }}</p>
      <RouterLink to="/" class="btn-primary btn-sm"><Icon name="home" :size="15" />去首页逛逛</RouterLink>
    </div>
    <template v-else>
      <section class="flex flex-wrap items-end gap-3">
        <div class="min-w-0 flex-1">
          <p v-reveal="0" class="flex items-center gap-2 text-[13px] text-ink-2">
            <UserAvatar v-if="data?.owner" :user="data.owner" :size="22" />
            <span>{{ data?.owner?.nickname || '' }} 分享的收藏</span>
          </p>
          <h1 v-reveal="1" class="mt-1.5 text-[clamp(24px,4.6vw,34px)] font-extrabold tracking-tight">
            <span v-if="data?.folder.emoji" class="mr-1">{{ data.folder.emoji }}</span><span class="text-gradient">{{ data?.folder.name || '…' }}</span>
          </h1>
          <p v-if="data" class="mt-1 text-sm text-mute">{{ data.items.length }} 个 Skill / 工具 / 模型</p>
        </div>
        <RouterLink v-reveal="2" to="/" class="btn-glass btn-sm"><Icon name="pocket" :size="15" />做自己的技能口袋</RouterLink>
      </section>

      <div v-if="!data" class="mt-5 grid grid-cols-2 gap-2.5 sm:gap-3.5 lg:grid-cols-4"><div v-for="n in 8" :key="n" class="skeleton-bar h-56 rounded-[12px]" /></div>
      <p v-else-if="!data.items.length" class="panel mt-5 px-6 py-12 text-center text-sm text-ink-2">这个分类里还没有条目</p>
      <div v-else class="mt-5 grid grid-cols-2 gap-2.5 sm:gap-3.5 lg:grid-cols-4">
        <ItemCard v-for="(it, i) in data.items" :key="it.id" :item="it" :index="i % 6" :base="`/s/${token}`" dense />
      </div>
    </template>

    <RouterView v-slot="{ Component }">
      <Transition name="sheet">
        <component :is="Component" v-if="Component" />
      </Transition>
    </RouterView>
  </div>
</template>
