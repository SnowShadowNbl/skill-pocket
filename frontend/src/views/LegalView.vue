<script setup>
import { computed } from 'vue'
import { RouterLink, useRoute } from 'vue-router'

const route = useRoute()
const isPrivacy = computed(() => route.path === '/privacy')
const UPDATED = '2026 年 11 月 4 日'
const siteHost = location.host
</script>

<template>
  <article class="panel mx-auto max-w-3xl p-6 sm:p-10">
    <div class="flex gap-2 text-sm">
      <RouterLink to="/terms" class="rounded-full px-3 py-1" :class="!isPrivacy ? 'bg-brand-soft font-semibold text-brand' : 'text-ink-2 hover:bg-white/70'">用户协议</RouterLink>
      <RouterLink to="/privacy" class="rounded-full px-3 py-1" :class="isPrivacy ? 'bg-brand-soft font-semibold text-brand' : 'text-ink-2 hover:bg-white/70'">隐私政策</RouterLink>
    </div>

    <template v-if="!isPrivacy">
      <h1 class="mt-5 text-2xl font-extrabold">Skill Pocket 用户协议</h1>
      <p class="mt-1 text-sm text-mute">更新日期：{{ UPDATED }}</p>
      <div class="legal">
        <h2>一、服务说明</h2>
        <p>Skill Pocket（{{ siteHost }}，以下简称「本站」）收录、整理公开的 Agent Skill、AI 模型、工具与开源项目信息，提供检索、榜单、收藏与使用记录等功能。条目内容来自 GitHub 等公开来源，部分介绍由 AI 自动整理，仅供参考，请以原项目说明为准。</p>
        <h2>二、账号</h2>
        <p>你可以用邮箱验证码登录，未注册的邮箱验证后自动注册。请妥善保管邮箱和密码，通过你的账号进行的操作视为你本人的行为。你可以随时在「我的 → 账号设置」中注销账号。</p>
        <h2>三、使用规范</h2>
        <p>使用本站时，你不得：发布违法、侵权、色情、暴力、广告引流或骚扰他人的内容；冒充本站或他人；用脚本批量注册、刷取验证码或接口；干扰本站正常运行。违反规范的内容可能被删除，账号可能被停用。</p>
        <h2>四、你提交的内容</h2>
        <p>你新增的 Skill 条目会公开展示并注明上传者昵称；你写的使用日志（评论）对所有访客可见。请确保提交的内容真实、合法，不侵犯他人权利。</p>
        <h2>五、第三方项目</h2>
        <p>本站收录的项目均属于其原作者，本站不对第三方项目的功能、安全性和许可证承担责任。安装和使用前请自行阅读原项目的说明和许可协议。</p>
        <h2>六、服务变更与免责</h2>
        <p>本站可能调整、暂停部分功能，会尽量提前在「更新日志」中说明。因不可抗力、网络或第三方服务原因造成的服务中断，本站不承担责任。</p>
        <h2>七、联系我们</h2>
        <p>对本协议有疑问，或发现违规内容，可以通过站内评论或站长公布的联系方式反馈。</p>
      </div>
    </template>

    <template v-else>
      <h1 class="mt-5 text-2xl font-extrabold">Skill Pocket 隐私政策</h1>
      <p class="mt-1 text-sm text-mute">更新日期：{{ UPDATED }}</p>
      <div class="legal">
        <h2>一、我们收集的信息</h2>
        <ul>
          <li><b>账号信息</b>：邮箱地址、昵称、头像颜色、密码（只保存不可逆的加密哈希）。</li>
          <li><b>登录记录</b>：登录设备类型（如 Windows · Chrome）、IP 地址、登录与活跃时间，用于账号安全和「登录设备」管理。</li>
          <li><b>你产生的内容</b>：收藏与收藏分类、收藏备注、使用日志（评论）、新增的条目、截图与长文识别时提交的内容。</li>
          <li><b>语音输入</b>：只用于实时转写成文字，音频不保存。</li>
          <li><b>访问记录</b>：无论是否登录，我们会在浏览器里保存一个随机的访客编号，并记录访问的页面、搜索词、复制 / 分享 / 收藏等操作、设备类型、来源网站、IP 地址及由 IP 推算的大致地区（省市级，由服务器离线查询，不使用定位权限）。用于防刷、安全审计和改进产品；明细保存 180 天，之后只保留不含个人信息的每日汇总。登录后，这个浏览器的访问记录会与你的账号关联。</li>
        </ul>
        <h2>二、我们如何使用</h2>
        <p>用于提供登录、收藏、评论、新增 Skill 等功能；发送登录验证码；防止验证码和接口被滥用；改进服务。我们不会出售你的个人信息。</p>
        <h2>三、第三方服务</h2>
        <ul>
          <li><b>腾讯云邮件推送</b>：向你的邮箱发送验证码。</li>
          <li><b>DeepSeek</b>：整理条目介绍、识别截图和长文、搜索关键词、昵称审核时，会把相关文字或图片发送给 AI 服务处理。</li>
        </ul>
        <h2>四、公开展示的信息</h2>
        <p>你的<b>昵称和头像</b>会显示在你的评论和你新增的条目上；<b>邮箱不会公开</b>，只有你本人和站长可见。</p>
        <h2>五、保存与删除</h2>
        <p>访问记录明细保存 180 天后自动删除。账号信息在你使用期间保存。注销账号后，收藏与收藏分类立即删除；评论和新增的条目保留并显示为「已注销用户」；邮箱解除绑定，可以重新注册。</p>
        <h2>六、你的权利</h2>
        <p>你可以在「我的」中查看自己的收藏、评论、提交记录，修改昵称和密码，退出其他设备，或注销账号。</p>
        <h2>七、安全</h2>
        <p>全站使用 HTTPS；密码与验证码只保存加密哈希；登录令牌只保存哈希值，可随时在「登录设备」中让其失效。</p>
      </div>
    </template>
  </article>
</template>

<style scoped>
.legal {
  margin-top: 24px;
  font-size: 14.5px;
  line-height: 1.85;
  color: var(--color-ink-2);
}
.legal h2 {
  margin: 22px 0 6px;
  font-size: 16px;
  font-weight: 700;
  color: var(--color-ink);
}
.legal ul {
  padding-left: 1.2em;
  list-style: disc;
}
.legal b {
  color: var(--color-ink);
}
</style>
