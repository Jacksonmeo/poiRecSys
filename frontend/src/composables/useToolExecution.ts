import type { ToolCallInfo, ToolExecution } from "@/types/agent"

/** Agent 工具的展示名称和辅助说明。 */
export const TOOL_META: Record<string, { label: string; hint: string }> = {
  query_poi: { label: "查询 POI 数据", hint: "空间查询" },
  spatial_density: { label: "执行空间密度分析", hint: "PostGIS 空间引擎" },
  recommend: { label: "生成地点推荐", hint: "推荐工具" },
  track: { label: "读取用户轨迹", hint: "轨迹分析" },
  analyze_site_selection: { label: "生成选址分析结果", hint: "选址分析工具" },
}

/** 将后端 bbox 参数压缩成时间线中的可读范围文案。 */
const formatBounds = (value: unknown) => {
  if (!value || typeof value !== "object") return "空间范围"
  const bounds = value as Record<string, unknown>
  const values = [bounds.min_lon, bounds.max_lon, bounds.min_lat, bounds.max_lat].map(Number)
  if (!values.every(Number.isFinite)) return "空间范围"
  return `${values[0].toFixed(2)}–${values[1].toFixed(2)} E · ${values[2].toFixed(2)}–${values[3].toFixed(2)} N`
}

/** 将工具调用参数转换为时间线中的紧凑标签。 */
export const formatToolArgs = (args: Record<string, unknown>): string[] => Object.entries(args)
  .filter(([, value]) => value !== "" && value !== undefined && value !== null)
  .map(([key, value]) => {
    if (key === "bbox") return formatBounds(value)
    if (key === "area_ids" && Array.isArray(value)) return `${value.length} 个候选区`
    if (key === "grid_size") return `grid=${String(value)}`
    if (key === "top_k") return `Top ${String(value)}`
    if (key === "category") return String(value)
    if (key === "user_id") return `用户 ${String(value)}`
    if (key === "session_id") return `会话 ${String(value)}`
    return `${key}=${String(value)}`
  })

/** 将工具返回的统计字段整理成时间线摘要。 */
export const formatToolResult = (result?: Record<string, unknown>) => {
  if (!result) return ""
  const parts = [
    typeof result.count === "number" ? `${result.count} 条结果` : "",
    typeof result.area_count === "number" ? `${result.area_count} 个候选区` : "",
    typeof result.metric_count === "number" ? `${result.metric_count} 项指标` : "",
    typeof result.flow_count === "number" ? `${result.flow_count} 条迁移关系` : "",
  ]
  return parts.filter(Boolean).join(" · ")
}

/** 管理一条 Agent 消息关联的工具调用状态。 */
export const useToolExecution = (executions: ToolExecution[]) => {
  /** 记录一个刚开始执行的工具调用。 */
  const addCall = (call: ToolCallInfo) => {
    executions.push({ tool: call.tool, args: call.args, status: "running" })
  }
  /** 将最近一个运行中的工具标记为成功并保存结果。 */
  const markSuccess = (result: Record<string, unknown>) => {
    const current = [...executions].reverse().find((item) => item.status === "running")
    if (current) {
      current.status = "success"
      current.result = result
    }
  }
  /** 将所有仍在运行的工具标记为失败。 */
  const markError = () => executions.forEach((item) => {
    if (item.status === "running") item.status = "error"
  })
  /** 在非流式回退场景中一次性写入已完成的工具调用。 */
  const applyCalls = (calls: ToolCallInfo[]) => {
    executions.length = 0
    calls.forEach((call) => executions.push({ tool: call.tool, args: call.args, status: "success" }))
  }
  return { addCall, markSuccess, markError, applyCalls }
}
