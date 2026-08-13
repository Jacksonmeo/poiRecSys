<script setup lang="ts">
import { storeToRefs } from "pinia"
import AgentWorkspace from "@/components/agent/AgentWorkspace.vue"
import { useWorkspaceStore } from "@/stores/workspace"

const workspace = useWorkspaceStore()
const { messages, sending } = storeToRefs(workspace)
</script>

<template>
  <aside class="workspace-agent" data-testid="workspace-agent-panel" aria-label="Agent 任务面板">
    <AgentWorkspace
      :messages="messages"
      :sending="sending"
      @clear="workspace.clear"
      @send="workspace.send"
    />
  </aside>
</template>

<style scoped>
.workspace-agent {
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  border-right: 1px solid #d8e3ef;
  background: rgba(255, 255, 255, .98);
}
</style>
