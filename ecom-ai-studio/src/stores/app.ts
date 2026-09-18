import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useAppStore = defineStore('app', () => {
  const sidebarCollapsed = ref(false)
  const sidebarExpanded = ref(false)

  function toggleSidebar() {
    sidebarCollapsed.value = !sidebarCollapsed.value
  }

  function expandSidebar() {
    sidebarExpanded.value = true
  }

  function collapseSidebar() {
    sidebarExpanded.value = false
  }

  return {
    sidebarCollapsed,
    sidebarExpanded,
    toggleSidebar,
    expandSidebar,
    collapseSidebar,
  }
})