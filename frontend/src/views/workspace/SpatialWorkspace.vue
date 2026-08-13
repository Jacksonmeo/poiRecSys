<script setup lang="ts">
import { storeToRefs } from "pinia"
import EvidencePanel from "@/components/workspace/EvidencePanel.vue"
import SpatialCanvas from "@/components/workspace/SpatialCanvas.vue"
import { useWorkspaceStore } from "@/stores/workspace"

const workspace = useWorkspaceStore()
const { artifacts } = storeToRefs(workspace)
</script>

<template>
  <main class="spatial-workspace" :class="{ 'has-evidence': artifacts.length }" data-testid="spatial-workspace">
    <SpatialCanvas />
    <EvidencePanel v-if="artifacts.length" />
  </main>
</template>

<style scoped>
.spatial-workspace { display: grid; height: 100%; min-height: 0; grid-template-columns: minmax(0, 1fr); overflow: hidden; border: 1px solid #d2deea; border-radius: 16px; background: #fff; box-shadow: 0 14px 38px rgba(38,57,88,.11); }
.spatial-workspace.has-evidence { grid-template-columns: minmax(0, 1fr) minmax(400px, 460px); }
@media (max-width: 1040px) { .spatial-workspace,.spatial-workspace.has-evidence { height: auto; min-height: 100%; grid-template-columns: minmax(0,1fr); grid-template-rows: minmax(620px,calc(100vh - 110px)) auto; overflow: auto; } .spatial-workspace :deep(.evidence-panel) { min-height: 480px; border-top: 1px solid #d8e3ef; border-left: 0; } }
@media (max-width: 760px) { .spatial-workspace,.spatial-workspace.has-evidence { display: flex; flex-direction: column; } .spatial-workspace :deep(.spatial-canvas) { min-height: 620px; } }
@media (max-height: 620px) and (min-width: 761px) { .spatial-workspace,.spatial-workspace.has-evidence { height: 520px; min-height: 520px; } }
</style>
