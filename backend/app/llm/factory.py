"""LLM 客户端工厂（Stage 4）。

按 settings.llm_provider 构造具体客户端（懒加载单例）。
- mock（默认）：规则路由模拟，无需任何外部依赖
- openai_compat：OpenAI 兼容 API（openai_compat.py 中实现）
"""

from app.core.config import settings
from app.llm.client import LLMClient
from app.llm.providers.mock import MockProvider

_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    """返回当前配置的 LLM 客户端（进程内单例，避免重复构造）。"""
    global _client
    if _client is None:
        if settings.llm_provider == "openai_compat":
            from app.llm.providers.openai_compat import OpenAICompatClient

            _client = OpenAICompatClient(
                base_url=settings.llm_base_url,
                api_key=settings.llm_api_key,
                model=settings.llm_model,
                timeout=settings.llm_timeout,
            )
        else:
            _client = MockProvider()
    return _client
