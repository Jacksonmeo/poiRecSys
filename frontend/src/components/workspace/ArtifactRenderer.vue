<script setup lang="ts">
import type { AgentArtifact } from "@/types/agent"
import SiteSelectionArtifactView from "@/components/artifact/SiteSelectionArtifactView.vue"

defineProps<{ artifact: AgentArtifact; selectedArea: string | null }>()
defineEmits<{ selectArea: [areaId: string] }>()
</script>

<template>
  <SiteSelectionArtifactView
    v-if="artifact.type === 'site_selection'"
    :artifact="artifact.data"
    :selected-area="selectedArea"
    @select-area="$emit('selectArea', $event)"
  />
</template>
