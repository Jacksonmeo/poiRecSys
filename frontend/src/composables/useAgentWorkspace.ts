import { storeToRefs } from "pinia"
import { useWorkspaceStore } from "@/stores/workspace"

/** 将工作台 Pinia 状态转换为组件可直接使用的响应式 Agent 工作区接口。 */
export const useAgentWorkspace = () => {
  const store = useWorkspaceStore()
  const { activeArtifact, artifacts, mapLayers, messages, selectedArea, sending } = storeToRefs(store)

  return {
    activeArtifact,
    artifacts,
    clear: store.clear,
    layers: mapLayers,
    messages,
    selectedArea,
    send: store.send,
    sending,
  }
}
