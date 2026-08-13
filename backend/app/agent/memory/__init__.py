"""对话记忆抽象层（Stage 4 Step 4）。

ConversationMemory 定义 get / append / clear 接口；
当前提供内存实现（InMemoryConversationMemory），未来可替换 Redis 实现，
只要保持接口不变即可。
"""

from app.agent.memory.base import ConversationMemory
from app.agent.memory.memory import InMemoryConversationMemory

__all__ = ["ConversationMemory", "InMemoryConversationMemory"]
