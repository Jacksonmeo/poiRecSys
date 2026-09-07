"""LLMIntentRouter：LLM Function Calling 意图识别（Stage 4）。

流程：system + tools schema + 历史 + user → LLM → tool_call → GeoResolver 解析地点
→ Intent。空间工具的 schema 对 LLM 只暴露 location（地点名），坐标解析由
GeoResolver 完成，LLM 不直接生成 bbox。LLM 不可用 / 输出非法（重试 1 次）
→ 降级规则路由 _route_intent，保证闭环。
"""

from app.agent.geo.resolver import geo_resolver
from app.agent.prompts.prompt import DEFAULT_BBOX, SYSTEM_PROMPT, Intent, _route_intent
from app.agent.registry import AgentTool, ToolRegistry
from app.llm.client import LLMClient
from app.llm.factory import get_llm_client
from app.llm.schemas import LLMMessage, LLMResponse, LLMToolCall

# 非法输出时最多请求次数（重试 1 次，仍失败降级规则路由）
_MAX_ATTEMPTS = 2
# 需要地点解析的空间工具：schema 用 location 替换 bbox
_LOCATION_TOOL_NAMES = {"query_poi", "spatial_density"}


def _llm_parameters(tool: AgentTool) -> dict:
    """对空间工具隐藏 bbox、暴露 location：LLM 只输出地点名，不生成坐标。"""
    if tool.name not in _LOCATION_TOOL_NAMES:
        return tool.parameters
    properties = {
        key: value
        for key, value in tool.parameters.get("properties", {}).items()
        if key != "bbox"
    }
    properties["location"] = {
        "type": "string",
        "description": "地点名称（如 涩谷 / 新宿 / 东京等），系统会自动解析为空间包围盒",
    }
    return {"type": "object", "properties": properties}


def _tool_schema(tool: AgentTool) -> dict:
    """AgentTool → OpenAI 函数声明格式（function calling tools 列表元素）。"""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": _llm_parameters(tool),
        },
    }


class LLMIntentRouter:
    """LLM 意图识别：函数调用输出 → 地点解析 → Intent；失败降级规则路由。"""

    def __init__(
        self,
        registry: ToolRegistry,
        client: LLMClient | None = None,
        resolver=None,
    ) -> None:
        """构造路由器：绑定工具注册表、LLM 客户端与地点解析器。"""
        self._registry = registry
        self._client = client or get_llm_client()
        self._resolver = resolver or geo_resolver

    def route(self, message: str, history: list[LLMMessage] | None = None) -> Intent:
        """识别意图。LLM 不可用或输出非法（重试 1 次）时降级规则路由。"""
        messages = self.build_messages(message, history)
        response = self.chat(messages, fallback_message=message)
        intent = self._parse(response)
        return intent if intent is not None else _route_intent(message)

    def chat(
        self,
        messages: list[LLMMessage],
        fallback_message: str,
    ) -> LLMResponse:
        """执行一次 LLM 推理并规范化 Tool Call，失败时返回规则路由结果。"""
        if not self._client.is_available():
            return self._fallback_response(messages, fallback_message)
        for _ in range(_MAX_ATTEMPTS):
            try:
                response = self._client.complete(messages, self.tools_schema())
            except Exception:
                # LLM 调用异常（网络/超时/解析失败）→ 重试
                continue
            normalized = self._normalize_response(response)
            if normalized is not None:
                return normalized
        return self._fallback_response(messages, fallback_message)

    def build_messages(self, message: str, history: list[LLMMessage] | None) -> list[LLMMessage]:
        """组装 LLM 输入：system prompt + 对话历史 + 当前用户消息。"""
        messages = [LLMMessage(role="system", content=SYSTEM_PROMPT)]
        if history:
            messages.extend(history)
        messages.append(LLMMessage(role="user", content=message))
        return messages

    def tools_schema(self) -> list[dict]:
        """把注册表全部工具导出为函数声明。"""
        return [_tool_schema(tool) for tool in self._registry.all()]

    # 保留旧私有名称，避免破坏现有调用方。
    _build_messages = build_messages
    _tools_schema = tools_schema

    def _normalize_response(self, response: LLMResponse) -> LLMResponse | None:
        """校验工具白名单并解析地点参数，同时保留 provider 的 call id。"""
        if not response.tool_calls:
            return response
        call = response.tool_calls[0]
        if self._registry.get(call.name) is None:
            return None
        intent = self._resolve_location(call.name, call.arguments)
        return LLMResponse(
            text=response.text,
            tool_calls=[
                LLMToolCall(
                    id=call.id,
                    name=intent.tool,
                    arguments=intent.args,
                )
            ],
        )

    @staticmethod
    def _fallback_response(
        messages: list[LLMMessage],
        fallback_message: str,
    ) -> LLMResponse:
        """把既有规则路由适配成统一 LLMResponse。"""
        if messages and messages[-1].role == "tool":
            return LLMResponse()
        intent = _route_intent(fallback_message)
        if not intent.tool:
            return LLMResponse(text=intent.text)
        return LLMResponse(
            tool_calls=[LLMToolCall(name=intent.tool, arguments=intent.args)]
        )

    def _parse(self, response: LLMResponse) -> Intent | None:
        """LLM 输出 → Intent；无工具调用返回文本 Intent；非法工具名返回 None（触发重试）。"""
        if not response.tool_calls:
            return Intent(tool="", args={}, text=response.text)
        call = response.tool_calls[0]
        if self._registry.get(call.name) is None:
            return None
        return self._resolve_location(call.name, call.arguments)

    def _resolve_location(self, tool_name: str, arguments: dict) -> Intent:
        """location → bbox：GeoResolver 解析；未知地点或缺失回退默认东京中心。"""
        args = dict(arguments)
        if tool_name in _LOCATION_TOOL_NAMES:
            location = args.pop("location", None)
            if location:
                args["bbox"] = self._resolver.resolve(location) or dict(DEFAULT_BBOX)
            elif tool_name == "spatial_density":
                # 密度分析必须有区域：LLM 未给位置时使用默认东京中心
                args["bbox"] = dict(DEFAULT_BBOX)
        return Intent(tool=tool_name, args=args)
