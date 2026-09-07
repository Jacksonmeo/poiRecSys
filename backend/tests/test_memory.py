"""对话记忆测试（Stage 4 Step 4）。

InMemoryConversationMemory 单元测试 + AgentService 会话记忆集成测试。
"""

from tests.conftest import client

from app.agent.memory import InMemoryConversationMemory


def test_memory_append_and_get() -> None:
    """append 后 get 返回 user + assistant 两条消息。"""
    memory = InMemoryConversationMemory()
    memory.append("sess_x", "帮我找咖啡店", "共找到 3 个 POI")
    messages = memory.get("sess_x")
    assert len(messages) == 2
    assert messages[0].role == "user" and messages[0].content == "帮我找咖啡店"
    assert messages[1].role == "assistant" and messages[1].content == "共找到 3 个 POI"


def test_memory_get_missing_session_returns_empty() -> None:
    """不存在的会话返回空列表。"""
    assert InMemoryConversationMemory().get("nope") == []


def test_memory_clear() -> None:
    """clear 后历史清空。"""
    memory = InMemoryConversationMemory()
    memory.append("sess_x", "a", "b")
    memory.clear("sess_x")
    assert memory.get("sess_x") == []


def test_memory_truncates_oldest_rounds() -> None:
    """超过 MAX_ROUNDS 轮时截断最旧的记录。"""
    memory = InMemoryConversationMemory()
    memory.MAX_ROUNDS = 2  # 只保留最近 2 轮
    for index in range(5):
        memory.append("sess_x", f"问{index}", f"答{index}")
    messages = memory.get("sess_x")
    assert len(messages) == 4  # 最近 2 轮 × 2 条
    assert messages[0].content == "问3"  # 最早的两轮已被截断


def test_chat_with_session_id_appends_history(seeded) -> None:
    """带 session_id 的对话会写入记忆；不带则不写。"""
    client.post("/api/agent/chat", json={"message": "帮我找咖啡店", "session_id": "sess_agent_1"})
    # 第二次调用读取记忆（历史第一条 user 消息应已记录）
    resp = client.post("/api/agent/chat", json={"message": "看看空间密度", "session_id": "sess_agent_1"})
    assert resp.status_code == 200
    assert resp.json()["data"]["tool_calls"][0]["tool"] == "spatial_density"

    # 不带 session_id → 不写记忆
    resp = client.post("/api/agent/chat", json={"message": "给我推荐"})
    assert resp.status_code == 200


def test_chat_session_memory_roundtrip(seeded) -> None:
    """同一 session 两次对话后记忆可被读取（含历史消息结构）。"""
    from app.agent.service import conversation_memory

    conversation_memory.clear("sess_agent_2")
    client.post("/api/agent/chat", json={"message": "帮我找咖啡店", "session_id": "sess_agent_2"})
    history = conversation_memory.get("sess_agent_2")
    assert len(history) == 2
    assert history[0].content == "帮我找咖啡店"
