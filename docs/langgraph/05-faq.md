# 05 · 常见问题 FAQ

> 学习/使用 LangGraph 过程中最常见的坑，按主题分类。遇到问题先来这里翻。

---

## 安装与版本

### Q1：装哪个版本？为什么项目写 `>=0.4.0,<1.0.0`？

LangGraph 0.4+ 的 `StateGraph` / `START` / `END` / `add_messages` 核心 API 非常稳定，
本项目在 0.6.x 上开发验证。限制 `<1.0.0` 防止 1.0 大版本 API 变动。

```bash
pip install "langgraph>=0.4.0,<1.0.0"
```

### Q2：`langgraph` 装上了，`langchain` 要装吗？

不需要。LangGraph 会自带 `langchain-core`（图运行需要它），但你不必显式安装
`langchain` 本体——GeoAgent 就只用了 `langgraph` 的图原语。

---

## State 与 Reducer

### Q3：为什么我的字段被后一个节点覆盖了？

因为该字段**没有 Reducer**。默认行为就是「覆盖」。需要合并（追加/累加）时
加 `Annotated[类型, 合并函数]`，例如 `Annotated[list[str], operator.add]`。

### Q4：`add_messages` 和 `operator.add` 选哪个？

- 用 **LangChain 消息**（`BaseMessage` 或 `{"role": ..., "content": ...}` 字典）
  → `add_messages`（会按消息 id 去重、自动转换格式）
- 用自己的 **Pydantic 模型**（如 GeoAgent 的 `LLMMessage`）→ `operator.add`
  （纯拼接，零转换）

> `add_messages` 收到不认识的类型会报错，这是最常见的一个坑。

### Q5：State 里能放 `set` 吗？

能。`set` 没有 Reducer 就是整体覆盖（`execute_tools` 返回新的完整集合即可），
GeoAgent 的 `seen_calls` 就是这么用的。注意：初始输入里也必须是 `set` 类型。

### Q6：节点返回的字典里能包含 State 里没有的键吗？

能，LangGraph 会把它加进 State。但建议保持 State 字段固定，新增字段先改
TypedDict——类型提示是图的可读性来源。

---

## 图结构与执行

### Q7：为什么 `add_conditional_edges` 的映射表报 KeyError？

路由函数返回的字符串**必须出现在映射表里**。GeoAgent 的映射表：
`{"execute_tools": "execute_tools", "end": END}`，路由只允许返回
`"execute_tools"` 或 `"end"`。返回别的值 → KeyError。

### Q8：图不结束 / 报 `GraphRecursionError`？

循环缺少终止条件。检查：
1. State 里有没有计数器（如 `step`），节点里有没有 `if step >= max: 结束`
2. 路由函数是否所有路径都能通向 `END`
3. 临时兜底：`app.invoke(input, {"recursion_limit": 50})` 调大上限（治标不治本）

### Q9：`invoke` 和 `stream` 结果不一样？

`stream(stream_mode="values")` 的**最后一个 yield** 就是最终 State，应该和
`invoke` 一致。如果只取第一个 yield，当然不一样——那只是第一步的现场。
GeoAgent 的 `iter_run` 用 `final_state = update` 持续更新，循环结束后
`final_state` 就是终态。

### Q10：节点里怎么拿到「本次请求」的参数（db、用户输入）？

通过 `config["configurable"]`。`invoke(input, {"configurable": {...}})`，
节点签名 `def node(state, config)` 里取。**不要**用全局变量——并发请求会串数据。

### Q11：为什么节点要用工厂函数（闭包）包一层？

当节点需要「构建图时就固定」的依赖（router、registry、上限）时，用闭包注入；
需要「每次运行才确定」的依赖（db、原始输入）时，用 config 注入。
两者结合，节点函数签名保持统一 `(state, config)`。

---

## 与项目其他部分的关系

### Q12：GeoAgent 的图为什么不用 `langgraph.prebuilt.ToolNode`？

`ToolNode` 是为 LangChain 的 `@tool` 装饰器设计的。项目用自己的
`AgentTool` 体系（`run(db, args)`），所以自实现了 `execute_tools` 节点，
逻辑也就十几行。**自己的体系 → 自己的节点，不强迁框架**。

### Q13：`InMemoryConversationMemory` 和 LangGraph 的记忆是一回事吗？

不是一套机制：
- `InMemoryConversationMemory`：项目自己的会话记忆，把 user/assistant 文本
  存进进程字典，下次请求拼进消息流
- LangGraph Checkpointer：保存**整个 State**（含工具调用、执行记录），
  按 `thread_id` 恢复，还能断点续跑

未来演进方向：把图 `compile(checkpointer=...)`，用 `thread_id` 当 session_id，
记忆和状态统一由 LangGraph 管理（见 03 篇第 6 节示例）。

### Q14：改了图，需要重新启动后端吗？

需要。`uvicorn --reload` 会自动重启；手动启动的话 Ctrl+C 后重跑。

---

## 调试技巧

### Q15：怎么可视化我的图？

```python
app = graph.compile()
# 输出 Mermaid 文本（0.4+ 支持）
print(app.get_graph().draw_mermaid())
```

把输出贴到 <https://mermaid.live> 即可看图。也可以用
`app.get_graph().draw_ascii()` 在终端直接画 ASCII 图。

### Q16：怎么逐步打印看执行过程？

```python
for update in app.stream(input, stream_mode="updates"):
    print(update)          # 每个节点返回的增量
```

比 `values` 模式更聚焦「这个节点写了什么」。

### Q17：节点抛异常了，怎么定位是哪个节点？

异常堆栈里会带节点名；也可以把节点包 try/except 打日志：

```python
def node(state, config):
    try:
        ...
    except Exception as exc:
        print(f"node failed: {exc}")
        raise
```

---

## 官方资料

- 概念文档：<https://langchain-ai.github.io/langgraph/concepts/>
- 教程（ReAct Agent 起步）：<https://langchain-ai.github.io/langgraph/tutorials/>
- API 参考：<https://langchain-ai.github.io/langgraph/reference/graphs/>
- LangGraph 官方 GitHub：<https://github.com/langchain-ai/langgraph>
