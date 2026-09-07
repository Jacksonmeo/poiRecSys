"""OpenAI 兼容 API 客户端（Stage 4 Step 3）。

通过 openai 官方 SDK + 可配置 base_url 支持任何 OpenAI 兼容服务
（OpenAI / DeepSeek / Moonshot / Qwen 等），不绑定单一模型。
"""

import json

from openai import OpenAI

from app.llm.client import LLMClient
from app.llm.schemas import LLMMessage, LLMResponse, LLMToolCall


class OpenAICompatClient(LLMClient):
    """OpenAI 兼容客户端：complete() 执行 chat.completions + function calling。"""

    name = "openai_compat"

    def __init__(self, base_url: str, api_key: str, model: str, timeout: int = 30) -> None:
        """构造客户端：保存连接参数，SDK 客户端懒初始化。"""
        self._base_url = base_url
        self._api_key = api_key
        self._model = model
        self._timeout = timeout
        self._client: OpenAI | None = None

    def is_available(self) -> bool:
        """base_url / api_key / model 三项齐全才可用，否则路由层降级规则路由。"""
        return bool(self._base_url and self._api_key and self._model)

    def _openai(self) -> OpenAI:
        """懒构造 SDK 客户端（配置齐全才会实例化）。"""
        if self._client is None:
            self._client = OpenAI(
                base_url=self._base_url,
                api_key=self._api_key,
                timeout=self._timeout,
            )
        return self._client

    def complete(self, messages: list[LLMMessage], tools: list[dict] | None = None) -> LLMResponse:
        """执行一次 chat.completions 调用并解析为统一 LLMResponse。"""
        payload: dict = {
            "model": self._model,
            "messages": [self._message_payload(message) for message in messages],
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        completion = self._openai().chat.completions.create(**payload)
        return self._parse(completion)

    def stream(self, messages: list[LLMMessage], tools: list[dict] | None = None):
        """真实流式对话：yield 文本增量（delta.content）。"""
        payload: dict = {
            "model": self._model,
            "messages": [self._message_payload(message) for message in messages],
            "stream": True,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        for chunk in self._openai().chat.completions.create(**payload):
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                yield delta.content

    def _parse(self, completion) -> LLMResponse:
        """SDK 响应 → 统一 LLMResponse；arguments JSON 非法时抛 ValueError（触发路由层重试）。"""
        message = completion.choices[0].message
        text = message.content or ""
        tool_calls = []
        for call in message.tool_calls or []:
            try:
                arguments = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError as exc:
                raise ValueError(f"LLM 返回的 arguments 非法 JSON: {exc}") from exc
            if not isinstance(arguments, dict):
                raise ValueError("LLM 返回的 arguments 不是对象。")
            tool_calls.append(
                LLMToolCall(
                    id=getattr(call, "id", None),
                    name=call.function.name,
                    arguments=arguments,
                )
            )
        return LLMResponse(text=text, tool_calls=tool_calls)

    @staticmethod
    def _message_payload(message: LLMMessage) -> dict:
        """把统一消息转换为 OpenAI Chat Completions 消息格式。"""
        payload: dict = {"role": message.role, "content": message.content}
        if message.role == "assistant" and message.tool_calls:
            payload["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments, ensure_ascii=False),
                    },
                }
                for call in message.tool_calls
            ]
        if message.role == "tool":
            payload["tool_call_id"] = message.tool_call_id
            if message.name:
                payload["name"] = message.name
        return payload
