<script setup lang="ts">
import { storeToRefs } from "pinia"
import ArtifactRenderer from "./ArtifactRenderer.vue"
import { useWorkspaceStore } from "@/stores/workspace"

const workspace = useWorkspaceStore()
const { artifacts, selectedArea } = storeToRefs(workspace)
</script>

<template>
  <aside class="evidence-panel" data-testid="evidence-panel" aria-label="结构化证据面板">
    <header class="evidence-panel__header">
      <div><span class="meta">结构化证据</span><strong>决策证据</strong></div>
      <span>{{ artifacts.length }} 份结果</span>
    </header>
    <div v-if="artifacts.length" class="evidence-panel__content">
      <ArtifactRenderer
        v-for="(artifact, index) in artifacts"
        :key="`${artifact.type}-${index}`"
        :artifact="artifact"
        :selected-area="selectedArea"
        @select-area="workspace.selectArea"
      />
    </div>
  </aside>
</template>

<style scoped>
.evidence-panel { display: flex; min-width: 0; min-height: 0; flex-direction: column; overflow: hidden; border-left: 1px solid #d8e3ef; background: #fff; }
.evidence-panel__header { display: flex; min-height: 52px; flex: 0 0 52px; align-items: center; justify-content: space-between; gap: 12px; padding: 0 14px; border-bottom: 1px solid #e1e9f2; }
.evidence-panel__header .meta,.evidence-panel__header strong { display: block; }
.evidence-panel__header .meta { color: #7789a5; font-family: var(--font-mono); font-size: 8px; letter-spacing: .1em; }
.evidence-panel__header strong { margin-top: 2px; color: #203047; font-size: 12px; }
.evidence-panel__header > span { padding: 4px 7px; border: 1px solid #dbe5ef; border-radius: 999px; color: #728198; background: #f7f9fc; font-family: var(--font-mono); font-size: 7px; }
.evidence-panel__content { min-width: 0; min-height: 0; flex: 1; overflow: auto; scrollbar-color: #c6d5e4 transparent; scrollbar-gutter: stable; scrollbar-width: thin; }
.evidence-panel__content :deep(.artifact-view__grid) { grid-template-columns: 1fr; }
.evidence-panel__content :deep(.metadata-card) { grid-template-columns: repeat(2, minmax(0, 1fr)); }
</style>
