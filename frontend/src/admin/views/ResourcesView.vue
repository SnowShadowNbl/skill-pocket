<script setup>
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import CodeLimitsPanel from '../components/CodeLimitsPanel.vue'
import RiskPanel from '../components/RiskPanel.vue'
import SchedulesPanel from '../components/SchedulesPanel.vue'
import ApiHealthPanel from '../components/ApiHealthPanel.vue'
import ClientErrorsPanel from '../components/ClientErrorsPanel.vue'
import ReleasesPanel from '../components/ReleasesPanel.vue'
import EmailLogPanel from '../components/EmailLogPanel.vue'
import NotificationLogPanel from '../components/NotificationLogPanel.vue'
import PushRunsPanel from '../components/PushRunsPanel.vue'
import AlertsPanel from '../components/AlertsPanel.vue'
import ResourcesPanel from '../components/ResourcesPanel.vue'
import ServiceHealthPanel from '../components/ServiceHealthPanel.vue'
import StoragePanel from '../components/StoragePanel.vue'

// 运行监控：服务状态（含备份、小程序配置）、告警、资源用量、存储与清理
const emit = defineEmits(['changed'])
const route = useRoute()
const router = useRouter()
const TABS = [['health', '服务状态'], ['alerts', '告警'], ['usage', '资源用量'], ['comms', '邮件与通知'], ['quality', '接口与版本'], ['risk', '风控与任务'], ['storage', '存储与清理']]
const tab = computed(() => (TABS.some((t) => t[0] === route.query.tab) ? route.query.tab : 'health'))
const sub = ref('email')
const SUBS = [['email', '邮件'], ['notify', '站内消息'], ['push', '每日推送']]
const qsub = ref('api')
const QSUBS = [['api', '接口健康'], ['errors', '客户端报错'], ['releases', '版本与部署']]
const rsub = ref('risk')
const RSUBS = [['risk', '风控'], ['codes', '验证码限制'], ['jobs', '定时任务']]
const setTab = (t) => router.replace({ query: { tab: t === 'health' ? undefined : t } })
</script>

<template>
  <div>
    <div class="flex flex-wrap items-center gap-3">
      <h1 class="m-0 text-xl font-semibold">运行监控</h1>
      <div class="seg ml-auto max-w-full overflow-x-auto [&>button]:shrink-0 [&>button]:whitespace-nowrap"><button v-for="t in TABS" :key="t[0]" :class="{ on: tab === t[0] }" @click="setTab(t[0])">{{ t[1] }}</button></div>
    </div>
    <ServiceHealthPanel v-if="tab === 'health'" @changed="emit('changed')" />
    <AlertsPanel v-else-if="tab === 'alerts'" @changed="emit('changed')" />
    <ResourcesPanel v-else-if="tab === 'usage'" @changed="emit('changed')" />
    <div v-else-if="tab === 'comms'">
      <div class="seg mt-3 max-w-full overflow-x-auto"><button v-for="t in SUBS" :key="t[0]" :class="{ on: sub === t[0] }" @click="sub = t[0]">{{ t[1] }}</button></div>
      <EmailLogPanel v-if="sub === 'email'" />
      <NotificationLogPanel v-else-if="sub === 'notify'" />
      <PushRunsPanel v-else />
    </div>
    <div v-else-if="tab === 'quality'">
      <div class="seg mt-3 max-w-full overflow-x-auto"><button v-for="t in QSUBS" :key="t[0]" :class="{ on: qsub === t[0] }" @click="qsub = t[0]">{{ t[1] }}</button></div>
      <ApiHealthPanel v-if="qsub === 'api'" />
      <ClientErrorsPanel v-else-if="qsub === 'errors'" />
      <ReleasesPanel v-else />
    </div>
    <div v-else-if="tab === 'risk'">
      <div class="seg mt-3 max-w-full overflow-x-auto"><button v-for="t in RSUBS" :key="t[0]" :class="{ on: rsub === t[0] }" @click="rsub = t[0]">{{ t[1] }}</button></div>
      <RiskPanel v-if="rsub === 'risk'" />
      <CodeLimitsPanel v-else-if="rsub === 'codes'" />
      <SchedulesPanel v-else />
    </div>
    <StoragePanel v-else />
  </div>
</template>
