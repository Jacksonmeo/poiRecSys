"""MockProvider：用规则路由模拟 LLM 函数调用（Stage 4）。

离线/未配置 API Key 时的默认客户端。将规则路由（prompts/prompt.py 的
_route_intent）包装成 LLMResponse，使 Agent 编排走与真实 LLM 完全相同的
"输出工具调用 → 执行 → 总结" 路径，保证闭环不依赖外部服务。
"""

from app.agent.prompts.prompt import REPLY_TEMPLATES, _route_intent
from app.llm.client import LLMClient
from app.llm.schemas import LLMMessage, LLMResponse, LLMToolCall


class MockProvider(LLMClient):
    """规则路由模拟 LLM：按关键词输出工具调用，未命中时输出兜底文本。"""

    name = "mock"

    def complete(self, messages: list[LLMMessage], tools: list[dict] | None = None) -> LLMResponse:
        """用规则路由模拟 LLM：按关键词输出工具调用，未命中输出兜底文本。"""
        # Tool 结果已回填时结束 Function Calling；离线模式的确定性总结由
        # AgentLoop 的 fallback summary 生成，避免重复选择同一个工具。
        if messages and messages[-1].role == "tool":
            return LLMResponse()

        # 取最后一条用户消息做规则路由（与 Stage 3 行为一致）
        user_text = next((m.content for m in reversed(messages) if m.role == "user"), "")
        intent = _route_intent(user_text)
        if not intent.tool:
            return LLMResponse(text=REPLY_TEMPLATES["fallback"])
        return LLMResponse(tool_calls=[LLMToolCall(name=intent.tool, arguments=intent.args)])
