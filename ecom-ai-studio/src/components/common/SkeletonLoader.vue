<script setup lang="ts">
import { cn } from '@/lib/utils'

defineProps<{
  width?: string
  height?: string
  rounded?: string
}>()
</script>

<template>
  <div
    :class="cn(
      'skeleton',
      width || 'w-full',
      height || 'h-48',
      rounded || 'rounded-xl',
    )"
  />
</template>