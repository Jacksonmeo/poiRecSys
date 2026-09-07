"""内存版会话记忆（Stage 4 Step 4）。

单机演示默认实现：进程内 dict 存储，最多保留最近 MAX_ROUNDS 轮对话。
未来替换 Redis 时只需新写一个 ConversationMemory 实现。
"""

from app.agent.memory.base import ConversationMemory
from app.llm.schemas import LLMMessage


class InMemoryConversationMemory(ConversationMemory):
    """进程内 dict 存储的会话记忆。"""

    # 每个会话最多保留的对话轮数（1 轮 = user + assistant 两条消息）
    MAX_ROUNDS = 8

    def __init__(self) -> None:
        """初始化进程内会话存储（session_id → 消息列表）。"""
        self._store: dict[str, list[LLMMessage]] = {}

    def get(self, session_id: str) -> list[LLMMessage]:
        """返回该会话历史副本（无历史返回空列表）。"""
        return list(self._store.get(session_id, []))

    def append(self, session_id: str, user_content: str, assistant_content: str) -> None:
        """追加一轮对话并截断最旧记录。"""
        messages = self._store.setdefault(session_id, [])
        messages.append(LLMMessage(role="user", content=user_content))
        messages.append(LLMMessage(role="assistant", content=assistant_content))
        limit = self.MAX_ROUNDS * 2
        if len(messages) > limit:
            del messages[: len(messages) - limit]

    def clear(self, session_id: str) -> None:
        """清空指定会话历史。"""
        self._store.pop(session_id, None)
