<script setup lang="ts">
import { ref, watch } from 'vue'
import { RouterView, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useAppStore } from '@/stores/app'
import AppSidebar from './AppSidebar.vue'
import AppHeader from './AppHeader.vue'
import AnnouncementBar from '../common/AnnouncementBar.vue'

const auth = useAuthStore()
const appStore = useAppStore()
const router = useRouter()

// 等待认证初始化完成后再判断
if (auth.authLoading) {
  watch(
    () => auth.authLoading,
    (val) => {
      if (!val && !auth.isLoggedIn) {
        router.push('/login')
      }
    },
  )
} else if (!auth.isLoggedIn) {
  router.push('/login')
}

const showAnnouncement = ref(true)
const announcementBarRef = ref<InstanceType<typeof AnnouncementBar> | null>(null)

// KeepAlive 缓存名单：这些页面切换时保留状态，避免重复渲染和数据请求
const cachedViews = ['HomeView', 'WorkspaceView', 'HistoryView', 'FavoritesView', 'TeamView', 'PurchaseView', 'AdminView', 'ProfileView', 'MyOrdersView', 'HelpCenterView', 'AiModelView', 'ChatGenView', 'ImageMergeView', 'ModelProductView', 'PlanAnalysisView', 'ProductReplaceView', 'PromptReverseView', 'TextToImageView']

function handleOpenAnnouncements() {
  showAnnouncement.value = true
  announcementBarRef.value?.openAllAnnouncements()
}
</script>

<template>
  <div class="flex h-screen bg-surface-light overflow-hidden">
    <AppSidebar />
    <div class="flex-1 flex flex-col min-w-0">
      <AnnouncementBar v-if="showAnnouncement" ref="announcementBarRef" @close="showAnnouncement = false" />
      <AppHeader @open-announcements="handleOpenAnnouncements" />
      <main class="flex-1 overflow-auto">
        <RouterView v-slot="{ Component }">
          <KeepAlive :include="cachedViews">
            <component :is="Component" />
          </KeepAlive>
        </RouterView>
      </main>
    </div>
  </div>
</template>