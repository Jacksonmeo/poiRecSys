# GeoAgent：Agentic GIS 空间决策平台

基于 **Vue 3 + FastAPI + PostgreSQL/PostGIS + LangGraph** 的 Agentic GIS 产品：
以自然语言驱动空间分析，Agent 自主编排 GIS 工具（POI 查询、空间密度、轨迹、推荐、
选址分析），将结构化结果实时渲染到交互式地图上。

> 当前为第六阶段完成后的状态：Agent 编排从自研 AgentLoop 迁移到 **LangGraph
> StateGraph**（图节点化：模型调用 / 工具执行 / 路由决策，保留 LLM 不可用时的
> 规则路由降级）；产品收敛为「Agent + 地图」双核心，其余业务（Dashboard、
> 模型实验、指标对比、离线训练）已整体移除。

## 架构总览

```mermaid
flowchart LR
    subgraph FE["前端 Vue3 + TypeScript + Vite"]
        W["SpatialWorkspace（Agent 对话 + 地图 + 证据）"]
        A["api/ Agent SSE 流式封装"]
        M["MapContainer → useMap（Mapbox GL）"]
        L["map/layers（poi / heatmap / trajectory / area）"]
    end

    subgraph BE["后端 FastAPI"]
        AG["agent/ LangGraph 编排"]
        G["graph/（StateGraph：call_model → execute_tools → route）"]
        RT["router_llm（函数调用 + 地点解析 + 降级）"]
        TG["tools/ ToolRegistry（5 个 GIS 工具）"]
        LLM["llm/（OpenAI 兼容 + Mock Provider）"]
    end

    subgraph DB["PostgreSQL / PostGIS"]
        PO["pois（geom POINT, GIST 索引）"]
        CH["checkins / sessions / users"]
        RR["recommendation_results"]
    end

    W --> A --> AG
    W --> M --> L
    AG --> G --> RT --> TG
    TG --> DB
    RT --> LLM
```

**Agent 推理循环（LangGraph 图）：**

```
START → call_model ──有工具调用（未超步数 / 未重复）──→ execute_tools ──→ call_model ...
                  └────────── 无工具调用 / 超限 / 重复 ──────────→ END（产出 reply）
```

- `call_model`：LLM 函数调用（失败自动重试 1 次）；LLM 不可用或输出非法时降级规则路由
- `execute_tools`：执行最新消息中的全部工具调用，回填 tool 结果消息
- `route_after_model`：根据最新消息是否携带工具调用决定走向
- 循环保护：步数上限（默认 3）+ 工具调用签名去重（防 LLM 死循环）

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | Vue 3.5（Composition API + TS）、Vite 6、Pinia、Vue Router 4、Element Plus、Mapbox GL 3 |
| 后端 | FastAPI、SQLAlchemy 2、Pydantic v2、GeoAlchemy2、**LangGraph** |
| 数据库 | PostgreSQL + PostGIS（SRID 4326，POI 含 GIST 空间索引） |
| LLM | OpenAI 兼容 API（OpenAI / DeepSeek / Moonshot / Qwen 等）；未配置时自动降级 Mock 规则路由 |
| 测试 | pytest（后端集成测试）、vitest + ESLint（前端） |

## 目录结构

```text
.
├── backend/
│   ├── app/
│   │   ├── agent/           # Agent 编排
│   │   │   ├── graph/       # LangGraph：state / nodes / builder / runner
│   │   │   ├── geo/         # GeoResolver 地点解析（LLM 不直接生成坐标）
│   │   │   ├── memory/      # 对话记忆抽象（内存实现，可换 Redis）
│   │   │   ├── prompts/     # System Prompt + 规则路由降级
│   │   │   └── tools/       # query_poi / spatial_density / recommend / track / analyze_site_selection
│   │   ├── llm/             # LLM 客户端层（OpenAI 兼容 + Mock + Factory）
│   │   ├── api/             # agent / poi / analysis / users / sessions / site-selection / health
│   │   ├── core/            # 配置 + 统一响应格式 + 全局异常
│   │   ├── db/              # SQLAlchemy 引擎与会话
│   │   ├── models/          # ORM：Poi / Checkin / User / UserSession / RecommendationResult
│   │   ├── repositories/    # 空间查询（PostGIS SQL 唯一归属地）
│   │   ├── schemas/         # Pydantic 响应模型 + 选址配置契约
│   │   ├── services/        # 查询服务层（编排，不含 SQL）
│   │   └── site_selection/  # 选址分析领域（agent 工具 + 地图图层数据源）
│   ├── migrations/          # 数据库迁移 SQL
│   ├── scripts/             # 会话构建 / 推荐结果生成 / 选址配置生成 / 数据审计
│   └── tests/               # pytest 集成测试
├── frontend/
│   └── src/
│       ├── api/             # agent（SSE）/ poi / spatial / trajectory / request
│       ├── components/      # agent / map / workspace / artifact / common
│       ├── composables/     # useAgentWorkspace / useMap / useToolExecution / usePanelResize
│       ├── map/layers/      # poiLayer / trajectoryLayer / heatmapLayer / areaFlowLayer / candidateAreaLayer
│       ├── types/           # agent / map / spatial / siteSelection 类型
│       ├── views/           # workspace（主页面）+ PoiMap / TrajectoryView / SpatialAnalysisView
│       └── styles/
└── docs/                    # Agent / PostGIS / 选址 / UI 相关文档
```

## 快速启动

### 1. 后端

```bash
cd backend
pip install -r requirements.txt
pip install -r requirements-dev.txt   # 测试依赖（pytest / httpx）
# 配置数据库连接：复制/编辑 backend/.env
#   DATABASE_URL=postgresql+psycopg://user:pass@host:5432/dbname
# LLM 配置（可选，缺省自动降级 Mock 规则路由）：
#   LLM_PROVIDER=openai_compat
#   LLM_BASE_URL=https://api.deepseek.com/v1
#   LLM_API_KEY=sk-xxx
#   LLM_MODEL=deepseek-chat
uvicorn app.main:app --reload --port 8000
```

接口文档：`http://127.0.0.1:8000/docs`

### 2. 前端

```bash
cd frontend
npm install
# 配置环境变量：复制 .env.example 为 .env，填入 Mapbox Token
#   VITE_MAPBOX_TOKEN=pk.xxxx
npm run dev
```

打开 `http://localhost:5173`，默认进入空间决策工作台。

## 测试与代码检查

```bash
# 后端接口测试（自动创建 poi_recommendation_test 测试库）
cd backend && python -m pytest

# 前端代码检查、类型构建与单元测试
cd frontend && npm run lint && npm run build && npm run test
```

## API 一览

所有接口统一返回 `{ code, message, data }` 格式：

| 接口 | 说明 |
|---|---|
| `POST /api/agent/chat` | Agent 对话（LangGraph 编排，返回 reply / tool_calls / map_layers / artifacts） |
| `POST /api/agent/chat/stream` | Agent 对话流式（SSE：tool_call → tool_result → text → done） |
| `GET /api/pois` | POI 列表（分页 + 类别筛选） |
| `GET /api/pois/spatial` | bbox 空间查询（GeoJSON FeatureCollection） |
| `GET /api/pois/nearby` | 半径查询（米制距离） |
| `GET /api/analysis/density` | 格网密度分析（heatmap 数据源） |
| `GET /api/users` | 用户列表（关键词搜索 + 分页） |
| `GET /api/sessions/{sid}/trajectory` | 会话轨迹点 |
| `POST /api/site-selection/analyze` | 选址分析（agent 工具的后端入口） |
| `GET /api/health/database` | 数据库健康检查 |

## Agent 工具

| 工具 | 说明 | 地图图层 |
|---|---|---|
| `query_poi` | 按类别 / bbox 查询 POI（地点名由 GeoResolver 解析，LLM 不生成坐标） | poi |
| `spatial_density` | 格网密度统计（热力图） | heatmap |
| `recommend` | 返回模型 Top-K 推荐 POI（含解释字段） | poi |
| `track` | 查询会话轨迹（签到序列） | trajectory |
| `analyze_site_selection` | 多候选区选址事实分析（指标 + 区域流向） | area / flow + Artifact |

## 文档

| 文档 | 内容 |
|---|---|
| `docs/stage3_agent_report.md` | Agent Tool Calling 层报告 |
| `docs/stage4_llm_design.md` / `docs/stage4_llm_report.md` | LLM Function Calling 设计稿与报告 |
| `docs/stage5_ui_redesign.md` / `docs/stage5_ui_report.md` | 空间工作台 UI 重构设计与实现 |
| `docs/stage2_postgis.md` | PostGIS 空间能力技术文档 |
| `docs/site_selection_flow_spec.md` | 选址区域流向分析规格 |
| `docs/retail_site_selection_*` | 选址数据审计与实施记录 |
