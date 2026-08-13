import type { SiteSelectionArtifact } from "./siteSelection"

export interface ToolCallInfo {
  tool: string
  args: Record<string, unknown>
}

export type AgentMapLayerType = "heatmap" | "poi" | "trajectory"

export interface AgentMapLayer {
  type: AgentMapLayerType
  data: Array<Record<string, unknown>>
}

export interface SiteSelectionAgentArtifact {
  type: "site_selection"
  data: SiteSelectionArtifact
}

export type AgentArtifact = SiteSelectionAgentArtifact
export type ToolStatus = "pending" | "running" | "success" | "error"

export interface ToolExecution {
  tool: string
  args: Record<string, unknown>
  status: ToolStatus
  result?: Record<string, unknown>
}

export interface AgentChatMessage {
  role: "user" | "assistant"
  content: string
  toolCalls?: ToolCallInfo[]
  executions?: ToolExecution[]
  artifacts?: AgentArtifact[]
  taskStatus?: ToolStatus
  mapLayerCount?: number
}

export interface AgentChatResponse {
  reply: string
  tool_calls: ToolCallInfo[]
  map_layers: AgentMapLayer[]
  artifacts: AgentArtifact[]
}
