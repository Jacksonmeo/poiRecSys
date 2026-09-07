"""ConversationMemory 抽象接口（Stage 4 Step 4）。

Agent 编排层只依赖 get / append / clear，具体存储（内存 / Redis / DB）
由实现决定，保证未来可替换。
"""

from abc import ABC, abstractmethod

from app.llm.schemas import LLMMessage


class ConversationMemory(ABC):
    """会话记忆抽象：按 session_id 存取对话历史。"""

    @abstractmethod
    def get(self, session_id: str) -> list[LLMMessage]:
        """返回会话历史（最近 N 轮，超长自动截断最旧）。"""

    @abstractmethod
    def append(self, session_id: str, user_content: str, assistant_content: str) -> None:
        """追加一轮对话（user + assistant 两条消息）。"""

    @abstractmethod
    def clear(self, session_id: str) -> None:
        """清空指定会话的历史。"""
