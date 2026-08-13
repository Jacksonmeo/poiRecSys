/**
 * Agent 对话 API 封装（Stage 3 非流式 + Stage 4 SSE 流式）。
 * 非流式响应由 request 拦截器解包为 data。
 */
import request from "./request"
import type { AgentChatResponse, ToolCallInfo } from "@/types/agent"

const BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000/api"

/** 发送自然语言消息（非流式）：返回 { reply, tool_calls, map_layers }。 */
export const sendAgentMessage = (message: string, sessionId = "") =>
  request.post<never, AgentChatResponse>("/agent/chat", { message, session_id: sessionId })

/** SSE 流式事件回调。 */
export interface AgentStreamHandlers {
  onToolCall?: (call: ToolCallInfo) => void
  onToolResult?: (result: Record<string, unknown>) => void
  onText?: (chunk: string) => void
  onDone?: (response: AgentChatResponse) => void
}

interface StreamEvent {
  kind: string
  data: Record<string, unknown>
}

/** 解析一个 SSE 文本块（event: + data: 两行）→ 事件。 */
const parseBlock = (block: string): StreamEvent | null => {
  let kind = ""
  let dataRaw = ""
  for (const line of block.split("\n")) {
    if (line.startsWith("event: ")) kind = line.slice(7)
    else if (line.startsWith("data: ")) dataRaw = line.slice(6)
  }
  if (!kind || !dataRaw) return null
  return { kind, data: JSON.parse(dataRaw) }
}

/**
 * SSE 流式发送（fetch + ReadableStream；POST 无法用 EventSource）。
 * 网络失败 / 非 200 / error 事件时抛异常，由调用方回退非流式接口。
 */
export const sendAgentMessageStream = async (
  message: string,
  sessionId: string,
  handlers: AgentStreamHandlers,
): Promise<void> => {
  const response = await fetch(`${BASE_URL}/agent/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, session_id: sessionId }),
  })
  if (!response.ok || !response.body) {
    throw new Error("流式接口不可用")
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ""

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const blocks = buffer.split("\n\n")
    buffer = blocks.pop() ?? ""
    for (const block of blocks) {
      const event = parseBlock(block)
      if (!event) continue
      if (event.kind === "tool_call") {
        handlers.onToolCall?.(event.data as unknown as ToolCallInfo)
      } else if (event.kind === "tool_result") {
        handlers.onToolResult?.(event.data)
      } else if (event.kind === "text") {
        handlers.onText?.((event.data.content as string) ?? "")
      } else if (event.kind === "done") {
        handlers.onDone?.(event.data as unknown as AgentChatResponse)
      } else if (event.kind === "error") {
        throw new Error((event.data.message as string) || "Agent 执行失败")
      }
    }
  }
}
