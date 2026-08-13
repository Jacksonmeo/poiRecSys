import { computed, reactive, ref } from "vue"
import { defineStore } from "pinia"
import { sendAgentMessage, sendAgentMessageStream } from "@/api/agent"
import { useToolExecution } from "@/composables/useToolExecution"
import type {
  AgentArtifact,
  AgentChatMessage,
  AgentChatResponse,
  AgentMapLayer,
  ToolCallInfo,
  ToolStatus,
} from "@/types/agent"

export interface WorkspaceTask {
  prompt: string
  stage: "understanding" | "tool" | "evidence" | "complete" | "error"
  status: ToolStatus
  tool?: string
}

/** 集中管理 Agent 对话、工具执行、artifact 与地图联动状态。 */
export const useWorkspaceStore = defineStore("workspace", () => {
  const messages = ref<AgentChatMessage[]>([])
  const artifacts = ref<AgentArtifact[]>([])
  const selectedArea = ref<string | null>(null)
  const mapLayers = ref<AgentMapLayer[]>([])
  const activeTask = ref<WorkspaceTask | null>(null)
  const agentOpen = ref(false)
  const sending = ref(false)
  let sessionId = crypto.randomUUID()

  /** 当前工作台默认展示的第一份 artifact 数据。 */
  const activeArtifact = computed(() => artifacts.value[0]?.data ?? null)

  /** 清空本次工作台会话，并生成新的 Agent session id。 */
  const clear = () => {
    messages.value = []
    artifacts.value = []
    selectedArea.value = null
    mapLayers.value = []
    activeTask.value = null
    sessionId = crypto.randomUUID()
  }

  /** 设置当前选中的候选区域，驱动表格与地图联动。 */
  const selectArea = (areaId: string) => {
    selectedArea.value = areaId
  }

  /** 打开或关闭悬浮 Agent 对话框。 */
  const toggleAgent = () => { agentOpen.value = !agentOpen.value }
  /** 关闭悬浮 Agent 对话框。 */
  const closeAgent = () => { agentOpen.value = false }

  /** 将 SSE 或非流式响应合并到当前助手消息和工作台状态。 */
  const applyResponse = (assistant: AgentChatMessage, response: AgentChatResponse) => {
    const nextArtifacts = response.artifacts ?? []
    assistant.content = response.reply
    assistant.toolCalls = response.tool_calls
    assistant.artifacts = nextArtifacts
    assistant.taskStatus = "success"
    assistant.mapLayerCount = response.map_layers.length
    mapLayers.value = response.map_layers
    artifacts.value = nextArtifacts
    const areas = nextArtifacts[0]?.data.candidate_areas ?? []
    if (!areas.some((area) => area.area_id === selectedArea.value)) {
      selectedArea.value = areas[0]?.area_id ?? null
    }
    activeTask.value = { ...activeTask.value!, stage: "complete", status: "success" }
  }

  /** 提交用户问题，优先走 SSE，失败时回退到非流式 Agent 接口。 */
  const send = async (message: string) => {
    if (sending.value || !message.trim()) return
    messages.value.push({ role: "user", content: message })
    sending.value = true
    activeTask.value = { prompt: message, stage: "understanding", status: "running" }
    const assistant = reactive<AgentChatMessage>({
      role: "assistant", content: "", toolCalls: [], executions: [], artifacts: [], taskStatus: "running",
    })
    messages.value.push(assistant)
    const execution = useToolExecution(assistant.executions!)
    let streamCompleted = false

    try {
      await sendAgentMessageStream(message, sessionId, {
        onToolCall: (call: ToolCallInfo) => {
          assistant.taskStatus = "success"
          activeTask.value = { prompt: message, stage: "tool", status: "running", tool: call.tool }
          execution.addCall(call)
        },
        onToolResult: (result) => {
          execution.markSuccess(result)
          if (activeTask.value) activeTask.value = { ...activeTask.value, stage: "evidence" }
        },
        onText: (chunk: string) => { assistant.content += chunk },
        onDone: (response) => {
          streamCompleted = true
          applyResponse(assistant, response)
        },
      })
      if (!streamCompleted) throw new Error("SSE stream ended before done event")
    } catch {
      try {
        const response = await sendAgentMessage(message, sessionId)
        execution.applyCalls(response.tool_calls)
        applyResponse(assistant, response)
      } catch {
        execution.markError()
        assistant.taskStatus = "error"
        assistant.content = assistant.content || "任务执行未完成，请调整问题后重试。"
        activeTask.value = { prompt: message, stage: "error", status: "error" }
      }
    } finally {
      sending.value = false
    }
  }

  return {
    activeArtifact,
    activeTask,
    agentOpen,
    artifacts,
    clear,
    closeAgent,
    mapLayers,
    messages,
    selectArea,
    selectedArea,
    send,
    sending,
    toggleAgent,
  }
})
