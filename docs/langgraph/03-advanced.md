# 03 · 进阶主题：Reducer / 流式 / 循环控制

> 前提：已读完 01、02 篇。本篇回答 LangGraph 里最容易困惑的几个深水区问题，
> 每个都有可运行示例。

---

## 1. Reducer 深入：覆盖 vs 合并

### 1.1 没有 Reducer 的字段：后写覆盖先写

```python
from typing import TypedDict
from langgraph.graph import StateGraph, START, END

class S(TypedDict):
    value: str

def node_a(state: S) -> dict:
    return {"value": "来自A"}

def node_b(state: S) -> dict:
    return {"value": "来自B"}   # 覆盖了 A 写的

graph = StateGraph(S)
graph.add_node("a", node_a)
graph.add_node("b", node_b)
graph.add_edge(START, "a")
graph.add_edge("a", "b")
graph.add_edge("b", END)
print(graph.compile().invoke({"value": "初始"}))
# {'value': '来自B'}   ← 初始和 A 都被 B 覆盖
```

### 1.2 有 Reducer 的字段：按规则合并

```python
import operator
from typing import Annotated, TypedDict

class S(TypedDict):
    value: Annotated[list[str], operator.add]   # 追加

# ... 同样的图 ...
print(graph.compile().invoke({"value": ["初始"]}))
# {'value': ['初始', '来自A', '来自B']}   ← 全部保留
```

### 1.3 三种常用 Reducer

| Reducer | 行为 | 典型用途 |
|---|---|---|
| （不写） | 覆盖 | 计数器、最终结果、配置 |
| `operator.add` | 拼接/相加 | 消息列表、数字累加 |
| `langgraph.graph.message.add_messages` | 按消息 id 合并/去重 | 标准 LangChain 消息流 |

> `add_messages` 官方最常用，但它要求消息对象能被 LangChain 识别（有 `type` 属性
> 或本身就是 `BaseMessage`）。GeoAgent 用自己的 `LLMMessage`，所以选
> `operator.add`——**理解每种 Reducer 的适用场景，比背 API 更重要**。

### 1.4 自定义 Reducer

Reducer 就是普通函数 `(old, new) -> merged`：

```python
def keep_largest(old: int, new: int) -> int:
    return max(old, new)

class S(TypedDict):
    best: Annotated[int, keep_largest]
```

---

## 2. invoke / stream / astream：三种执行方式

| 方法 | 返回 | 用途 |
|---|---|---|
| `app.invoke(input, config)` | 最终 State（一个 dict） | 同步接口，只要最终结果 |
| `app.stream(input, config, stream_mode=...)` | 生成器，逐步 yield | 同步流式（如 SSE 后端） |
| `app.ainvoke / app.astream` | 异步版本 | FastAPI async 接口 |

### 2.1 stream_mode 三选一

```python
# 模式 1：values —— 每个节点跑完后，yield 完整 State
for state in app.stream(input, stream_mode="values"):
    print(state["step"])          # 每步都能看到全部字段

# 模式 2：updates —— 每个节点跑完后，yield 该节点返回的增量
for update in app.stream(input, stream_mode="updates"):
    # update 形如 {"call_model": {"step": 1, ...}}
    print(update["call_model"])   # 只有这个节点写的东西

# 模式 3：messages —— 专为 LLM 消息设计，yield 消息级增量
for chunk in app.stream(input, stream_mode="messages"):
    print(chunk)                  # (消息对象, 元数据)
```

**怎么选**：
- 想看「每一步完整现场」→ `values`（GeoAgent 用这个还原事件）
- 只关心「每个节点新增了什么」→ `updates`
- 要做 LLM 逐 token 打字机 → `messages`

---

## 3. 条件边的三种写法

### 3.1 映射表 + 路由函数（项目用法）

```python
def route(state) -> str:
    return "tools" if state["messages"][-1].tool_calls else "end"

graph.add_conditional_edges(
    "call_model",
    route,
    {"tools": "execute_tools", "end": END},   # 返回值 → 目标
)
```

### 3.2 路由函数直接返回节点对象（省略映射表）

```python
def route(state) -> str:
    if ...: return "execute_tools"
    return END          # 直接返回 END 哨兵，不需要映射表

graph.add_conditional_edges("call_model", route)
```

### 3.3 按路径列表分派（多个节点共享同一路由）

```python
graph.add_conditional_edges("call_model", route, ["execute_tools", "summarize", END])
# route 返回 "execute_tools" / "summarize" / END
```

---

## 4. 循环与终止：为什么我的图不结束？

LangGraph 没有「禁止循环」——图天然支持环，框架只兜底一个
`recursion_limit`（默认 25 次节点执行，超了抛 `GraphRecursionError`）。

**好实践：把终止条件放进 State，用条件边判断**（GeoAgent 的两把锁）：

```python
class AgentState(TypedDict):
    step: int
    seen_calls: set[str]

def call_model(state) -> dict:
    if state["step"] >= MAX_STEPS:      # 锁1：步数上限
        return {"reply": fallback(state["executions"])}
    response = llm.chat(...)
    if repeat(response, state["seen_calls"]):   # 锁2：重复调用
        return {"reply": fallback(state["executions"])}
    ...
```

> 教训：不要把终止条件只写在路由函数里，**节点的前置检查**同样重要——
> 路由只决定「下一步去哪」，节点内检查决定「这次还干不干」。

---

## 5. config 与 configurable：运行时依赖怎么传

节点签名固定为 `(state, config)`。**与本次请求相关的依赖**（数据库会话、
用户 ID、原始输入）放 `config["configurable"]`：

```python
# runner 侧
config = {"configurable": {"db": db, "input_message": message}}
app.invoke(input_state, config)

# 节点侧
def node(state, config):
    db = config["configurable"]["db"]
```

**与请求无关的依赖**（路由、工具注册表、上限）用闭包注入（02 篇的工厂函数）。

> 为什么不用全局变量？全局变量在并发请求下会互相污染；config 每个请求独立，
> 天然线程安全。

---

## 6. 持久化与 Checkpointer（未来扩展方向）

默认图跑完就丢。要支持「断点续跑 / 多轮记忆 / 人机审核」，用 checkpointer：

```python
from langgraph.checkpoint.memory import InMemorySaver

app = graph.compile(checkpointer=InMemorySaver())
config = {"configurable": {"thread_id": "会话ID"}}   # thread_id 区分会话

app.invoke(input1, config)   # 第一轮
app.invoke(input2, config)   # 第二轮：自动带上第一轮的 State
```

这正是本项目 `InMemoryConversationMemory` 想解决的问题——未来可以换成
checkpointer，把记忆交给 LangGraph 管理（见 05 篇 FAQ）。

---

## 7. LangGraph 与 LangChain 的关系

- **LangChain**：工具、模型封装、提示词等「零件」生态
- **LangGraph**：编排框架，负责「流程」——可以完全不依赖 LangChain 的零件

GeoAgent 的做法（也是官方推荐的最小依赖路径）：
**只用 LangGraph 的图原语**（StateGraph / START / END / Reducer），
LLM 调用用自己的 `LLMClient`，工具用自己的 `ToolRegistry`，
完全不引入 `langchain` 的 tool 装饰器。好处：依赖少、类型自己掌控。

> 想用 LangChain 生态也可以：`from langchain_core.tools import tool` 装饰
> 函数后直接当节点用，`langgraph.prebuilt.ToolNode` 还能自动执行工具。
> 两者不冲突，按需选择。

---

## 8. 一个完整的「多节点真实感」示例：带持久化的问答图

```python
"""综合示例：记忆 + 条件路由 + checkpointer"""
from typing import Annotated, TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import InMemorySaver

class ChatState(TypedDict):
    messages: Annotated[list, add_messages]   # 用官方的消息 Reducer

def assistant(state: ChatState) -> dict:
    last = state["messages"][-1]
    return {"messages": [{"role": "assistant", "content": f"你说了：{last.content}"}]}

graph = StateGraph(ChatState)
graph.add_node("assistant", assistant)
graph.add_edge(START, "assistant")
graph.add_edge("assistant", END)

app = graph.compile(checkpointer=InMemorySaver())
config = {"configurable": {"thread_id": "session-1"}}

app.invoke({"messages": [{"role": "user", "content": "你好"}]}, config)
result = app.invoke({"messages": [{"role": "user", "content": "还记得上一句吗"}]}, config)
for m in result["messages"]:
    print(f"{m.type}: {m.content}")
# human: 你好
# ai: 你说了：你好
# human: 还记得上一句吗
# ai: 你说了：还记得上一句吗
```

注意：这里 `add_messages` 要求消息是 dict 或 LangChain 消息——`{"role":..., "content":...}`
的 dict 会被自动转换成 `HumanMessage` / `AIMessage` 对象，所以取角色要用
`m.type`（值是 `"human"` / `"ai"`）而不是 `m.role`。这也是它和 `operator.add`
的又一区别：`operator.add` 不转换类型，`add_messages` 会转换。

下一篇 [04-exercises.md](./04-exercises.md) 动手练习。
