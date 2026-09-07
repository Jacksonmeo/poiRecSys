# Agent 修改日志 — 后端

本文档记录 Claude Code Agent 对后端代码的所有修改。

---

## 2026-07-15：Stage 6 — Agentic GIS 重构（LangGraph 编排 + 产品收敛）

### 修改概述

产品收敛为「Agent + 地图」双核心：删除与 Agent/地图无关的模块（metrics /
recommend API、metrics_service、exports、RecModel、Utils、dashboard 配套），
Agent 推理循环从自研 AgentLoop 迁移到 LangGraph StateGraph。

### 修改文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `app/agent/graph/state.py` | 新建 | AgentState（messages / executions / seen_calls / step / reply） |
| `app/agent/graph/nodes.py` | 新建 | call_model / execute_tools 节点工厂 + 路由决策 |
| `app/agent/graph/builder.py` | 新建 | StateGraph 构建与编译（含步数与去重保护） |
| `app/agent/graph/runner.py` | 新建 | AgentRunner（兼容原 AgentLoop 的 run / iter_run 接口） |
| `app/agent/loop.py` | 删除 | 自研循环被 LangGraph 图替换 |
| `app/agent/service.py` | 修改 | 改用 AgentRunner，SSE 事件契约不变 |
| `app/api/metrics.py` | 删除 | 模型指标接口（dashboard 配套） |
| `app/api/recommend.py` | 删除 | 推荐结果接口（model-lab 配套） |
| `app/services/metrics_service.py` | 删除 | 指标服务（dashboard 配套） |
| `app/data/metrics.json` | 删除 | 指标 mock 数据 |
| `requirements.txt` | 修改 | 新增 `langgraph>=0.4.0,<1.0.0` |
| `tests/test_agent_loop.py` | 重写 | 适配 AgentRunner（含 iter_run 事件序断言） |
| `tests/test_recommend_api.py` | 删除 | 随 recommend API 移除 |
| `tests/conftest.py` | 拆解 | seed_data 拆为 4 个种子函数 |

### 关键决策

1. **LangGraph 图结构**：`START → call_model → (route) → execute_tools → call_model → … → END`，
   步数上限与工具调用去重内置于节点逻辑
2. **不引入 langchain 工具生态**：execute_tools 直接调用既有 ToolRegistry
   （run(db, args)），保持最小改动
3. **事件契约不变**：iter_run 通过 `stream_mode="values"` 的状态快照差值还原
   tool_call → tool_result 事件，前端 SSE 协议零改动
4. **降级链保留**：LLM 不可用 / 输出非法时规则路由兜底，Mock Provider 离线可用
5. **多工具并行**：execute_tools 执行 LLM 返回的全部工具调用（原实现只取第一个）
6. **函数规范**：全部保留函数 ≤100 行并补齐中文 docstring；超长函数（如
   `build_config`、`run_audit`、`render_markdown`、`seed_data`）拆分为小函数

---

## 2026-07-11：POI 模块数据库迁移（CSV → PostgreSQL）

### 修改概述

将 `GET /api/pois` 及相关接口的数据源从 Mock CSV 文件迁移到 PostgreSQL 数据库。

### 修改文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `backend/app/core/__init__.py` | 新建 | 核心配置包初始化 |
| `backend/app/core/config.py` | 新建 | 环境变量与配置管理（pydantic-settings） |
| `backend/app/db/__init__.py` | 新建 | 数据库包初始化 |
| `backend/app/db/database.py` | 新建 | SQLAlchemy 引擎、会话管理与依赖注入 |
| `backend/app/models/__init__.py` | 新建 | ORM 模型包初始化 |
| `backend/app/models/poi.py` | 新建 | POI ORM 模型（映射 `pois` 表） |
| `backend/app/schemas/__init__.py` | 修改 | 更新包文档说明 |
| `backend/app/schemas/poi.py` | 新建 | POI Pydantic 响应模型（含旧前端兼容字段） |
| `backend/app/services/poi_service.py` | 修改 | 新增 DB 查询函数，保留 CSV 回退函数 |
| `backend/app/api/poi.py` | 修改 | 新增 DB 会话依赖注入和响应模型 |
| `backend/app/api/health.py` | 新建 | 数据库健康检查接口 |
| `backend/app/main.py` | 修改 | 注册 health 路由器 |
| `backend/requirements.txt` | 修改 | 新增 SQLAlchemy, psycopg, geoalchemy2, pydantic-settings |
| `backend/.env` | 新建 | PostgreSQL 连接配置 |

### 关键决策

1. **数据库连接**：使用 `psycopg` 3.x（二进制版），连接字符串格式 `postgresql+psycopg://`
2. **ORM 风格**：SQLAlchemy 2.x 声明式（Mapped + mapped_column）
3. **Schema**：Pydantic v2，使用 `from_attributes=True` 从 ORM 实例构建
4. **向后兼容**：PoiResponse 包含 `computed_field` 提供旧字段名（`poi_id`, `name`, `category`, `lng`, `lat`, `address`）
5. **分层保持**：Router → Service → ORM 三层，SQL 查询不写入 Router
6. **其他模块不受影响**：`recommend_service` 仍使用 CSV 回退函数 `get_poi_by_id`
7. **geam 不返回**：ORM 定义 `geom` 字段但 Schema 不序列化，只返回 `latitude`/`longitude`

### 技术要点

- `get_db()` 使用 Generator 模式实现 FastAPI 依赖注入
- `_MAX_LIMIT = 5000` 防止全表扫描
- 数据库异常通过 `SQLAlchemyError` 捕获并转为 HTTP 500
- `pool_pre_ping=True` 确保连接池中连接有效
- `expire_on_commit=False` 防止提交后属性过期

---

## 2026-07-11：display_name 字段贯通（ORM → API → 前端）

### 修改概述

数据库 `pois` 表新增 `display_name VARCHAR(255)` 列，贯通到 API 响应和前端展示。

### 修改文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `backend/app/models/poi.py` | 修改 | 新增 `display_name` 映射列，更新 `__repr__` |
| `backend/app/schemas/poi.py` | 修改 | 新增 `display_name` 字段；`name` computed_field 改用 display_name 优先 |

### 关键变更

1. **ORM 模型**：新增 `display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)`
2. **Pydantic Schema**：
   - `display_name: str | None = None` 作为数据库原生字段返回
   - `name` computed_field 改为三级优先级：
     1. `display_name`（数据库填充）
     2. `{venue_category} · {venue_id[-6:]}`（兜底）
     3. 仅 `venue_id[-6:]`（最终兜底）
3. **向后兼容**：`name` 字段仍存在，前端旧代码无需修改即可使用更好的展示名称
## 2026-07-15：RecModel 全量推荐结果入库与推荐 API 数据库化

### 修改概述

完成数据库 `sessions` 到 RecModel T10e-2 的离线推理链路，并将结果全量写入
`recommendation_results`。推荐 API 已不再读取 Mock CSV，而是分页查询数据库。

### 修改文件

| 文件 | 操作 | 说明 |
|------|------|------|
| `RecModel/src/infer_sessions.py` | 新增 | 重建训练词表、加载 T9 checkpoint、执行 T10e-2 重排；补充中文模块和关键逻辑注释 |
| `backend/scripts/generate_recommendations.py` | 新增 | 从数据库读取 session，最后一点作为 target，批量导出 CSV 并通过 `--write-db` 入库 |
| `backend/migrations/20260715_recommendation_results.sql` | 新增 | 创建结果表，并兼容旧表的 `candidate_poi_id/rank_no/created_at` 字段 |
| `backend/app/models/recommendation_result.py` | 新增 | 推荐结果 ORM 映射 |
| `backend/app/services/recommend_service.py` | 修改 | 推荐摘要分页、详情 POI 拼装、历史轨迹排除真实目标点 |
| `backend/app/api/recommend.py` | 修改 | 推荐列表分页查询及数据库异常处理 |
| `backend/app/core/config.py` | 修改 | 新增当前推荐模型名称配置 |
| `backend/README.md` | 修改 | 推荐模块数据源更新为 PostgreSQL |
| `docs/user-trajectory-database-integration.md` | 修改 | 增加迁移和离线推理运行说明 |

### 全量运行结果

- 数据库 session：79,312 条
- 可推理 session：46,402 条
- 目标 POI 超出训练词表：21,173 条
- 最后历史 POI 超出训练词表：11,737 条
- 每个可推理 session 生成 Top-10，共写入 464,020 条推荐结果
- 同时导出 `backend/exports/recommendation_results_TKY.csv`

### 验证

- RecModel checkpoint smoke test 通过，词表为 7,840 个 POI、187 个类别
- Python `compileall` 通过
- 数据库中 46,402 个 session 的候选数均为 10，重复 rank 数为 0
- `GET /api/recommendations?limit=2` 返回 200，总数为 46,402
- 推荐详情接口返回 200，包含去除目标点后的历史轨迹、真实目标和 10 个候选

---
