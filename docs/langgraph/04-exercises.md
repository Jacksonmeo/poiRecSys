# 04 · 动手练习（从简单到复杂，含答案要点）

> 建议：先自己写，卡住再看「答案要点」。所有练习独立可运行，
> 用 `python 练习文件.py` 执行。练习 4 需要动 GeoAgent 项目代码。

---

## 练习 1：三节点线性图（热身）

**要求**：State 含 `text` 字段。三个节点依次在文本后追加 `"→A"`、`"→B"`、`"→C"`，
最后打印最终 State。

<details>
<summary>答案要点（点击展开）</summary>

```python
from typing import TypedDict
from langgraph.graph import StateGraph, START, END

class S(TypedDict):
    text: str

def append_a(state: S) -> dict: return {"text": state["text"] + "→A"}
def append_b(state: S) -> dict: return {"text": state["text"] + "→B"}
def append_c(state: S) -> dict: return {"text": state["text"] + "→C"}

g = StateGraph(S)
g.add_node("a", append_a)
g.add_node("b", append_b)
g.add_node("c", append_c)
g.add_edge(START, "a"); g.add_edge("a", "b"); g.add_edge("b", "c"); g.add_edge("c", END)
print(g.compile().invoke({"text": "起点"}))
# {'text': '起点→A→B→C'}
```

</details>

---

## 练习 2：条件分支（天气决定穿什么）

**要求**：State 含 `weather: str`（`"sunny"` / `"rain"` / `"cold"`）。
一个 `decide` 节点，根据天气路由到三个不同的建议节点，最后输出建议。

<details>
<summary>答案要点（点击展开）</summary>

```python
from typing import TypedDict
from langgraph.graph import StateGraph, START, END

class S(TypedDict):
    weather: str
    advice: str

def decide(state: S) -> str:
    return state["weather"]            # 返回目标节点名

def sunny(state: S) -> dict: return {"advice": "穿短袖"}
def rain(state: S) -> dict: return {"advice": "带伞"}
def cold(state: S) -> dict: return {"advice": "穿外套"}

g = StateGraph(S)
g.add_node("sunny", sunny); g.add_node("rain", rain); g.add_node("cold", cold)
g.add_edge(START, "decide")   # 注意：decide 是路由函数，不是节点！
g.add_conditional_edges("decide", decide, {"sunny": "sunny", "rain": "rain", "cold": "cold"})
g.add_edge("sunny", END); g.add_edge("rain", END); g.add_edge("cold", END)
```

> 坑：`decide` 直接作为节点函数也行，但更规范的做法是把路由函数放在
> `add_conditional_edges` 里，节点只做「干活」的事。上面写法里 `decide` 被
> 当作节点注册了吗？没有——`add_conditional_edges` 的第一个参数是**源节点名**，
> 所以必须先把 `decide` 用 `add_node` 注册（或者换一种写法，见下）。

```python
# 更清晰的写法：decide 是真实节点，先算好建议，再路由
def decide(state: S) -> dict:
    return {"advice": {"sunny": "穿短袖", "rain": "带伞", "cold": "穿外套"}[state["weather"]]}

g.add_node("decide", decide)
g.add_edge(START, "decide")
g.add_conditional_edges("decide", lambda s: s["weather"], {"sunny": END, "rain": END, "cold": END})
```

</details>

---

## 练习 3：最简 ReAct Agent（核心练习）

**要求**：实现一个图：`call_model ⇄ execute_tools`，工具是一个「加法计算器」。
LLM 用假函数模拟：第一轮输出 `{"tool": "calculator", "args": {"a": 2, "b": 3}}`，
第二轮输出最终答案 `{"answer": "5"}`。要求：

1. 消息列表用 `Annotated[list[str], operator.add]`
2. 路由函数判断最后一条消息是否以 `"TOOL:"` 开头
3. 工具结果消息格式：`"TOOL: calculator → 5"`

<details>
<summary>答案要点（点击展开）</summary>

```python
import operator
from typing import Annotated, TypedDict
from langgraph.graph import StateGraph, START, END

class AgentState(TypedDict):
    messages: Annotated[list[str], operator.add]

calls = 0
def fake_llm(messages):
    global calls
    calls += 1
    if calls == 1:
        return {"tool": "calculator", "args": {"a": 2, "b": 3}}
    return {"answer": "5"}

def call_model(state: AgentState) -> dict:
    result = fake_llm(state["messages"])
    if "answer" in result:
        return {"messages": [f"ANSWER: {result['answer']}"]}
    return {"messages": [f"TOOL: {result['tool']} {result['args']}"]}

def execute_tools(state: AgentState) -> dict:
    # 从最后一条消息解析出工具调用
    last = state["messages"][-1]                 # "TOOL: calculator {'a': 2, 'b': 3}"
    _, tool_name, args_str = last.split(" ", 2)
    args = eval(args_str)                         # 练习用 eval，生产环境别这么干！
    result = args["a"] + args["b"]
    return {"messages": [f"RESULT: {result}"]}

def route(state: AgentState) -> str:
    return "tools" if state["messages"][-1].startswith("TOOL:") else "end"

g = StateGraph(AgentState)
g.add_node("call_model", call_model)
g.add_node("execute_tools", execute_tools)
g.add_edge(START, "call_model")
g.add_conditional_edges("call_model", route, {"tools": "execute_tools", "end": END})
g.add_edge("execute_tools", "call_model")

app = g.compile()
result = app.invoke({"messages": ["用户: 2+3=?"]})
print(result["messages"])
# ['用户: 2+3=?', 'TOOL: calculator ...', 'RESULT: 5', 'ANSWER: 5']
```

**对照**：这就是 GeoAgent 图（02 篇）的迷你版——`call_model`、`execute_tools`、
`route` 三个函数一一对应。

</details>

---

## 练习 4：给 GeoAgent 加一个「时间查询」工具（项目实战）

**背景**：GeoAgent 的图是通用的（execute_tools 遍历所有工具调用），
加工具**不需要改图**，只需要三处改动。

**要求**：新增 `current_time` 工具：无参数，返回当前时间字符串。

<details>
<summary>答案要点（点击展开）</summary>

**第 1 步**：新建 `backend/app/agent/tools/time_tool.py`：

```python
"""CurrentTimeTool：返回服务器当前时间（演示工具）。"""

from datetime import datetime
from sqlalchemy.orm import Session
from app.agent.registry import AgentTool


class CurrentTimeTool(AgentTool):
    """无参数工具：返回当前时间文本。"""

    name = "current_time"
    description = "返回服务器当前时间"
    parameters = {"type": "object", "properties": {}}

    def run(self, db: Session, args: dict) -> dict:
        args = self.validate(args)
        return {"type": "time", "current_time": datetime.now().isoformat(timespec="seconds")}
```

**第 2 步**：注册进 `backend/app/agent/service.py` 的 `build_default_registry`：

```python
from app.agent.tools.time_tool import CurrentTimeTool   # 新增导入

def build_default_registry(extra_tools=()):
    registry = ToolRegistry()
    tools = (QueryPOITool(), SpatialAnalysisTool(), RecommendTool(), TrackTool(), CurrentTimeTool())
    ...
```

**第 3 步**（可选）：LLM 提示词里介绍新工具（`prompts/prompt.py` 的
`SYSTEM_PROMPT`），并给 Mock 规则路由加关键词（`INTENT_KEYWORDS`）。

**验证**：`python -m pytest tests/test_agent_loop.py`，或直接对话
「现在几点」看是否触发 `current_time`。

> 关键领悟：**图是通用的执行框架，业务能力都在工具里**。这就像给电脑加
> 外设——主板（图）不用动，插上（注册）就能用。

</details>

---

## 练习 5（选做）：把练习 3 加上步数上限

**要求**：给练习 3 加 `step` 字段，`call_model` 最多跑 3 次，超过返回兜底文本
`"FAILED: 超时"`，且图必须能正常结束（不抛异常）。

<details>
<summary>答案要点（点击展开）</summary>

```python
class AgentState(TypedDict):
    messages: Annotated[list[str], operator.add]
    step: int

def call_model(state: AgentState) -> dict:
    if state["step"] >= 3:
        return {"messages": ["ANSWER: FAILED 超时"], "step": state["step"] + 1}
    result = fake_llm(state["messages"])
    if "answer" in result:
        return {"messages": [f"ANSWER: {result['answer']}"], "step": state["step"] + 1}
    return {"messages": [f"TOOL: {result['tool']} {result['args']}"], "step": state["step"] + 1}
```

注意：`step` 没有 Reducer，`call_model` 每次都返回**完整的新值**
`state["step"] + 1`，覆盖旧值即可。

</details>

---

## 练习完成后的自测清单

- [ ] 能说出 State / Node / Edge / 条件边 / Reducer 的含义
- [ ] 能解释 `Annotated[list, operator.add]` 和普通字段的区别
- [ ] 能画出 GeoAgent 的图（三个节点 + 两条边 + 一个循环）
- [ ] 知道 `invoke` 和 `stream(stream_mode="values")` 的区别
- [ ] 知道怎么给 GeoAgent 加一个工具（不用改图）
- [ ] 知道为什么 `step` / `seen_calls` 能防死循环

全部打勾 → 你已经入门 LangGraph 了，遇到问题看 [05-faq.md](./05-faq.md)。
