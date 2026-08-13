"""LLMClient 抽象基类（Stage 4）。

不绑定任何具体模型/厂商：Agent 编排层只依赖 complete() / is_available()，
具体实现放在 providers/ 目录（OpenAI 兼容、Mock 等）。
"""

from abc import ABC, abstractmethod

from app.llm.schemas import LLMMessage, LLMResponse


class LLMClient(ABC):
    """LLM 客户端统一接口。"""

    name: str = "base"

    @abstractmethod
    def complete(self, messages: list[LLMMessage], tools: list[dict] | None = None) -> LLMResponse:
        """发起一次非流式对话。

        messages: 完整对话历史（system + user + assistant…）
        tools: OpenAI 格式的函数声明列表；为 None 表示不启用函数调用
        返回: 统一 LLMResponse（文本回复或工具调用）
        """

    def stream(self, messages: list[LLMMessage], tools: list[dict] | None = None):
        """流式对话（可选实现）：yield 文本增量。

        默认回退一次性 complete；支持真实流式的 provider 可覆盖此方法。
        """
        response = self.complete(messages, tools)
        if response.text:
            yield response.text

    def is_available(self) -> bool:
        """客户端是否可用（配置缺失/密钥为空时返回 False 触发规则路由降级）。"""
        return True
