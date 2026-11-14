<script setup>
import { onBeforeUnmount, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { authState, isAdminUser, logout, requireLogin } from '../composables/auth'
import { favState } from '../composables/favorites'
import { toast } from '../composables/toast'
import { adminBadge } from '../composables/adminSummary'
import { openFeedback } from '../composables/feedback'
import Icon from './Icon.vue'
import UserAvatar from './UserAvatar.vue'

const router = useRouter()
const open = ref(false)
const root = ref(null)

async function doLogout() {
  open.value = false
  await logout()
  favState.map = {}
  favState.count = null
  toast('已退出登录', 'success', 1500)
  router.push('/')
}

function onDoc(e) {
  if (open.value && root.value && !root.value.contains(e.target)) open.value = false
}
addEventListener('pointerdown', onDoc, true)
onBeforeUnmount(() => removeEventListener('pointerdown', onDoc, true))
</script>

<template>
  <div ref="root" class="relative">
    <button v-if="!authState.user" class="btn-glass btn-sm" @click="requireLogin()">
      <Icon name="login" :size="15" />登录
    </button>
    <template v-else>
      <button
        class="flex h-10 cursor-pointer items-center gap-2 rounded-full py-1 pr-2.5 pl-1 transition-colors duration-300 hover:bg-white/70"
        :aria-expanded="open"
        aria-haspopup="menu"
        :aria-label="`账号菜单：${authState.user.nickname}`"
        @click="open = !open"
      >
        <span class="relative">
          <UserAvatar :user="authState.user" :size="32" />
          <span v-if="adminBadge()" class="absolute -top-0.5 -right-0.5 h-2.5 w-2.5 rounded-full border-2 border-white bg-brand-2" :title="`管理系统里有 ${adminBadge()} 件待处理`" />
        </span>
        <span class="hidden max-w-[7rem] truncate text-sm font-medium lg:inline">{{ authState.user.nickname }}</span>
        <Icon name="chevron-down" :size="14" class="hidden text-mute lg:block" />
      </button>
      <Transition name="drop">
        <div
          v-if="open"
          class="glass-strong absolute top-full right-0 z-50 mt-2 w-60 rounded-2xl p-1.5 shadow-[0_18px_40px_-14px_rgb(11_47_122/0.5)]"
          role="menu"
          @click="open = false"
        >
          <div class="flex items-center gap-3 px-3 pt-2.5 pb-3">
            <UserAvatar :user="authState.user" :size="40" />
            <div class="min-w-0">
              <p class="truncate font-semibold">{{ authState.user.nickname }}</p>
              <p class="truncate text-xs text-mute">{{ authState.user.email || (authState.user.role === 'admin' ? '超级管理员' : '') }}</p>
            </div>
          </div>
          <div class="border-t border-line pt-1">
            <RouterLink to="/pocket" class="menu-row" role="menuitem"><Icon name="heart" :size="16" />我的收藏</RouterLink>
            <RouterLink to="/me?tab=settings" class="menu-row" role="menuitem"><Icon name="lock" :size="16" />账号设置</RouterLink>
            <a v-if="isAdminUser()" href="/admin" class="menu-row" role="menuitem">
              <Icon name="shield" :size="16" />管理系统
              <span v-if="adminBadge()" class="ml-auto rounded-full bg-brand-2 px-1.5 text-[11px] font-bold text-white" :title="`待审核 + 新反馈共 ${adminBadge()} 件`">{{ adminBadge() }}</span>
            </a>
            <button class="menu-row w-full" role="menuitem" @click="openFeedback()"><Icon name="message" :size="16" />反馈与建议</button>
          </div>
          <div class="mt-1 border-t border-line pt-1">
            <button class="menu-row w-full text-danger" role="menuitem" @click="doLogout"><Icon name="arrow-left" :size="16" />退出登录</button>
          </div>
        </div>
      </Transition>
    </template>
  </div>
</template>

<style scoped>
.menu-row {
  display: flex;
  align-items: center;
  gap: 10px;
  height: 40px;
  padding: 0 12px;
  border-radius: 12px;
  font-size: 14px;
  cursor: pointer;
  transition: background-color 0.2s;
}
.menu-row:hover {
  background: var(--color-brand-soft);
}
.drop-enter-active,
.drop-leave-active {
  transition: opacity 0.18s ease, transform 0.28s cubic-bezier(0.16, 1, 0.3, 1);
  transform-origin: top right;
}
.drop-enter-from,
.drop-leave-to {
  opacity: 0;
  transform: translateY(-4px) scale(0.97);
}
</style>
