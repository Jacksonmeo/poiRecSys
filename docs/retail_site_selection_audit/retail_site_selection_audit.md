# GeoAgent 零售选址 MVP 可行性审计

> 审计目标：将现有通用空间查询/下一 POI 推荐项目收敛为“基于开放空间数据和历史行为数据的东京咖啡店选址分析 Agent”。  
> 审计日期：2026-08-03  
> 审计范围：当前工作区中的前端、后端、ORM、Agent、Tool、Service、Repository、测试、迁移、数据制品和文档。  
> 审计约束：只审计，不修改现有代码；本文件是本次唯一新增文件。

## 1. 最终结论

**结论：现有项目适合升级为该 MVP，但只能定位为“历史开放数据驱动的候选商圈相对比较工具”，不能定位为真实商业决策系统。**

适合升级的原因是，五项指标所需的最小底层信号已经存在：`Poi.venue_category/latitude/longitude/geom`、`Checkin.user_id/venue_id/utc_timestamp/session_id/sequence_no`、`UserSession` 以及 PostGIS 查询底座；Agent 的 `AgentTool`、`ToolRegistry`、`AgentService`、SSE 和 Mapbox 点/热力/线渲染链路也已经打通。证据见 `backend/app/models/poi.py::Poi`、`backend/app/models/checkin.py::Checkin`、`backend/app/models/session.py::UserSession`、`backend/app/repositories/poi_repository.py`、`backend/app/agent/registry.py::AgentTool`、`backend/app/agent/service.py::AgentService`、`frontend/src/composables/useMap.ts::useMap`。

不能直接发布为可信 MVP 的原因是，当前没有选址领域的 Repository/Service/Schema/Tool，没有经过版本化的候选商圈 Polygon、类别口径、权重和归一化规则；现有 `map_layers` 也不支持 Polygon、区域流向和候选区高亮。尤其是 `GeoResolver` 的四个区域只是面积不等的 bbox，原始数量不能直接比较。证据见 `backend/app/agent/geo/resolver.py::_PLACE_INDEX`、`backend/app/agent/schemas.py::MapLayer`、`frontend/src/types/agent.ts::AgentMapLayerType`。

因此本审计**不输出当前商圈排名**。在候选边界、咖啡竞品分类（至少要决定 `Coffee Shop` 是否与 `Café` 合并）、指标方向、权重和归一化版本未确定前，任何综合分和推荐理由都会是人为拼装，而不是现有项目中可复核的结果。

### 1.1 可行性判断

| 项目 | 判断 | 依据 |
|---|---|---|
| 竞品密度 | 可计算代理指标 | `Poi.venue_category` + `Poi.geom`；当前只有精确类别/bbox 查询，见 `Poi` 与 `query_by_bbox()` |
| 交通便利度 | 可计算“交通 POI 可达性代理” | 类别中存在 `Train Station`、`Subway`、`Bus Station` 等；没有班次、线路或客流字段 |
| 业态配套度 | 可计算“POI 业态组合代理” | `Poi.venue_category` 可做白名单密度/多样性；没有消费关联、营业时间和质量字段 |
| 历史访问活跃度 | 可计算历史签到代理 | `Checkin.user_id/utc_timestamp/venue_id` 可按区域聚合；不能称为实际或实时客流 |
| 历史区域流入强度 | 可计算历史签到转移代理 | `Checkin.session_id/sequence_no` + POI 坐标可计算跨区进入；不能称为真实出行总量 |
| 综合评分/排名 | 技术可行，当前口径缺失 | 需要版本化 Polygon、分类、方向、权重、归一化；当前无对应配置或服务 |
| 地图最终输出 | 部分可复用，必须扩展 | POI、heatmap 可用；Polygon、flow、highlight 缺失 |

### 1.2 审计证据限制

- 当前 Python 解释器未安装 `psycopg`，执行 `python -m pytest --collect-only -q` 在 `backend/tests/conftest.py:16` 因 `ModuleNotFoundError: psycopg` 中止；`psycopg[binary]` 虽已声明在 `backend/requirements.txt`，但本机运行环境未就绪。
- 后端 API 当时未运行，不能通过 `backend/app/api/health.py::database_health()` 对实际 PostgreSQL 实例做在线抽样。因此“表内实际行数”没有冒充为已在线核验；本报告的数据规模来自仓库现存真实制品 `Utils/dataset_TSMC2014_TKY.csv`、`backend/exports/sessions_TKY.csv`、`backend/exports/session_points_TKY.csv`、`backend/exports/recommendation_results_TKY.csv`，表结构能力来自 ORM 和迁移。
- 前端 `npm run lint` 已在本次审计中通过。前端没有测试脚本或测试文件，`frontend/package.json` 只提供 `dev/build/preview/lint`。

## 2. 当前架构与可直接复用能力

### 2.1 数据模型

| 模块 | 可复用字段/职责 | 选址 MVP 中的用途 | 限制 |
|---|---|---|---|
| `backend/app/models/poi.py::Poi` | `venue_id`、`display_name`、`venue_category_id`、`venue_category`、`latitude`、`longitude`、`geom` | 竞品、交通、配套、地图 POI、空间归属 | 只有点/类别；无地址、品牌、评分、营业时间、规模 |
| `backend/app/models/checkin.py::Checkin` | `user_id`、`venue_id`、`timezone_offset`、`utc_timestamp`、`session_id`、`sequence_no` | 历史活跃度、区域进入转移、时段聚合 | 无 `dataset`；不是客流传感器数据 |
| `backend/app/models/session.py::UserSession` | `session_id`、`user_id`、`start_time`、`end_time`、`checkin_count`、`dataset` | 限定 TKY、有序转移、会话覆盖率 | 24 小时切分是工程规则，不是一次真实行程 |
| `backend/app/models/recommendation_result.py::RecommendationResult` | `session_id`、`target_poi_id`、`poi_id`、`rank`、`score`、`model_name` | 模型中心、可选的模型覆盖诊断 | 是下一 POI 候选，不是选址适宜度或商业需求 |
| `backend/app/models/user.py::User` | 匿名 `user_id` | 去重历史用户数 | 无人口画像，不能推断客群属性 |

### 2.2 Repository、Service 与空间接口

以下能力可直接复用，但不能直接代替五项指标的聚合查询：

- `backend/app/repositories/poi_repository.py::query_by_bbox()`：`ST_Intersects` + 可选 `venue_category` 精确过滤，可用于取样/地图点；默认 `MAX_SPATIAL_LIMIT=2000`，不适合用返回列表长度做商圈全量计数。
- `backend/app/repositories/poi_repository.py::query_by_radius()`：`ST_DWithin`/`ST_Distance` 的 geography 米制距离，可复用于交通设施距离衰减。
- `backend/app/repositories/poi_repository.py::query_density_grid()`：`ST_SnapToGrid` + `COUNT`，可复用其 PostGIS 写法；当前统计全部 POI，不能传类别，也不统计 checkin 权重。
- `backend/app/services/spatial_service.py::validate_bbox()`、`get_pois_in_bbox()`、`get_nearby_pois()`、`get_density_grid()`：参数校验和响应组装方式可复用。
- `backend/app/services/poi_service.py::get_pois()`、`get_categories()`、`get_poi_by_venue_id()`：类别枚举、POI 详情和地图点信息可复用。
- `backend/app/services/session_service.py::get_session_points()`：已有 `Checkin → Poi` JOIN 和稳定排序，可复用字段约定，但区域流入必须改为数据库聚合，不能逐 session 调用此函数造成 N+1。
- `backend/app/services/user_service.py::get_user_checkins()`：证明 checkin 与 POI 可联合返回，但其职责是单用户列表，不是区域聚合。

现有可直接调用的接口：

| 接口 | 当前实现 | 可复用方式 |
|---|---|---|
| `GET /api/pois` | `backend/app/api/poi.py::list_pois()` | 类别/POI 探索，不用于全量统计 |
| `GET /api/pois/categories` | `list_categories()` | 配置竞品/交通/配套分类前的数据探查 |
| `GET /api/pois/spatial` | `query_pois_by_bbox()` | POI 点图层；注意 2,000 默认/5,000 上限 |
| `GET /api/pois/nearby` | `query_pois_by_radius()` | 交通设施距离取样 |
| `GET /api/analysis/density` | `backend/app/api/analysis.py::query_density()` | 当前仅全 POI heatmap |
| `GET /api/users/{uid}/checkins` | `backend/app/api/users.py::list_user_checkins()` | 行为明细探查，不用于区域批量聚合 |
| `GET /api/users/{uid}/sessions` | `list_user_sessions()` | 模型/数据中心 |
| `GET /api/sessions/{sid}/trajectory` | `backend/app/api/sessions.py::get_session_trajectory()` | 单 session 轨迹验证 |
| `GET /api/recommendations*` | `backend/app/api/recommend.py` | 下一 POI 模型中心，不作为选址分数 |
| `POST /api/agent/chat`、`/chat/stream` | `backend/app/api/agent.py` | 复用 Agent/SSE 外壳；需扩展结构化分析 artifact |

### 2.3 Agent 与 Tool

- `backend/app/agent/registry.py::AgentTool.validate()`、`AgentTool.run()` 和 `ToolRegistry` 可直接作为 `SiteSelectionTool` 基类/注册中心。
- `backend/app/agent/router_llm.py::_tool_schema()` 可直接把新增 Tool 转成 Function Calling schema。
- `backend/app/agent/service.py::AgentService.chat()`、`chat_stream()` 和 `backend/app/agent/stream.py::sse_format()` 可复用同步/SSE 编排。
- `backend/app/agent/service.py::build_map_layers()` 可保留为 Tool 结果到地图协议的唯一适配点，但必须增加选址结果分支。
- 当前 `build_default_registry()` 只注册 `QueryPOITool`、`SpatialAnalysisTool`、`RecommendTool`、`TrackTool`；没有选址分析工具。
- 当前 Agent 只把 Tool 结果转成 `reply` 和 `map_layers`，没有把五维指标/排名作为可渲染结构返回。证据是 `backend/app/agent/schemas.py::ChatResponse` 只有 `reply/tool_calls/map_layers`，`AgentService._run_intent()` 也没有 artifact 字段。

### 2.4 前端与地图

- `frontend/src/views/agent/AgentView.vue` 已是左 Agent、右地图的主工作区，最适合作为唯一 MVP 页面。
- `frontend/src/composables/useAgentWorkspace.ts::useAgentWorkspace()` 已处理 SSE、非流式回退、会话 ID 和图层更新。
- `frontend/src/components/map/MapLayerRenderer.vue::applyLayers()` 已有按 `type` 分派的入口。
- `frontend/src/components/map/MapContainer.vue` 和 `frontend/src/composables/useMap.ts::useMap()` 已封装 Mapbox 生命周期、加载竞态、fitBounds、popup、POI/轨迹/heatmap 更新。
- `frontend/src/map/layers/poiLayer.ts`、`heatmapLayer.ts`、`trajectoryLayer.ts` 可继续复用，不需要重写地图基础设施。

## 3. 数据库与真实数据支撑能力

### 3.1 表结构是否足够

**五项指标本身不要求新增业务数据表。** `pois + checkins + sessions` 已能计算五项历史代理指标；`recommendation_results` 不必进入核心评分。字段证据如下：

| 指标 | 必需关联 | 当前字段 |
|---|---|---|
| 竞品/交通/配套 | 商圈几何 × POI 点 × 类别 | `Poi.geom`、`Poi.venue_category`、`Poi.venue_id` |
| 历史访问活跃度 | 签到 × POI 点 × 时间/用户 | `Checkin.venue_id/user_id/utc_timestamp` + `Poi.geom` |
| 历史区域流入 | 会话内相邻签到 × 两端 POI 点 | `Checkin.session_id/sequence_no/venue_id` + `Poi.geom` |

但是存在三个 P0 数据工程缺口：

1. `backend/scripts/build_sessions.py::build_sessions()` 只构建内存对象，`write_csv_outputs()` 只写 `sessions_TKY.csv/session_points_TKY.csv`；当前脚本没有向 `sessions` 插入、也没有回填 `checkins.session_id/sequence_no`。这与 `docs/user-trajectory-database-integration.md` 中“写 sessions 并回填 checkins”的描述相冲突。区域流入上线前必须让 session 持久化链路可重放并做一致性校验。
2. `backend/migrations/` 只有 sessions、recommendation_results 和质量检查增量 SQL，没有 `users/checkins/pois/geom/GIST` 的完整初始迁移。`Poi.geom` 注释声称已有 GIST，但仓库内没有可复现 DDL；见 `backend/app/models/poi.py::Poi.geom` 与 `backend/migrations/`。
3. `Utils/seperate.py` 用 `drop_duplicates(subset=["venueId"])` 任取同一 venue 的第一条坐标/类别写入 `pois`。原始 TKY 制品中有 3,468 个 venue 出现坐标变体、511 个 venue 出现类别变体，因此首条取值规则必须作为已知数据质量风险，而不是默认为精准门店位置。

### 3.2 仓库数据制品画像

数据制品与导入字段的关系可由 `Utils/seperate.py` 第 25-43 行（POI）和第 46-70 行（checkin）复核。只读统计结果如下：

| 制品 | 审计结果 |
|---|---|
| `Utils/dataset_TSMC2014_TKY.csv` | 573,703 条签到、2,293 名匿名用户、61,858 个 POI、247 类；时间 2012-04-03 至 2013-02-16 |
| `backend/exports/sessions_TKY.csv` | 79,312 个有效 session，最短 2 点、最长 311 点、平均 6.711 点 |
| `backend/exports/session_points_TKY.csv` | 532,290 个被分配到有效 session 的签到点 |
| `backend/exports/recommendation_results_TKY.csv` | 464,020 行、46,402 个 session、Top-10、模型 `T10e2_CausalMemoryFusion` |

原始数据没有 POI 名称字段，只有 `venueId/venueCategoryId/venueCategory/latitude/longitude/...`，见 `RecModel/dataset/README.md` 和 `Utils/seperate.py`。因此 `Poi.display_name` 的真实品牌名覆盖率无法由该制品证明，不能基于它可靠计算连锁品牌数或品牌集中度。

### 3.3 四个内置 bbox 的数据覆盖（只作可行性证据，不是最终评分）

下表按 `GeoResolver._PLACE_INDEX` bbox、按 `Utils/seperate.py` 的“每 venue 首条 POI 坐标”口径计算。竞品组合列仅展示 `Coffee Shop + Café` 的数据覆盖；是否合并必须由后续版本化分类配置决定，当前 Agent 只把“咖啡店”映射为 `Coffee Shop`（`backend/app/agent/prompts/prompt.py::CATEGORY_KEYWORDS`）。

| 区域 | bbox 约面积 km² | POI | `Coffee Shop` | `Café` | 交通 POI白名单 | 历史签到 | 历史跨区进入 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 涩谷 | 2.009 | 2,326 | 45 | 156 | 52 | 24,921 | 9,014 |
| 新宿 | 4.017 | 3,164 | 55 | 138 | 127 | 39,571 | 14,931 |
| 银座 | 5.022 | 3,739 | 108 | 170 | 218 | 34,745 | 12,692 |
| 池袋 | 4.015 | 1,606 | 27 | 81 | 71 | 22,417 | 7,608 |

交通白名单统计使用数据中真实存在的 `Train Station/Bus Station/Subway/Light Rail/Ferry/Taxi/Airport/Travel & Transport`；这是审计用数据探查，不是项目现有配置。

**重要：bbox 面积从约 2.0 到 5.0 km² 不等。** 例如合并 `Coffee Shop + Café` 后，原始竞品数是涩谷 201、银座 278，但按 bbox 面积的密度约为涩谷 100.0/km²、银座 55.4/km²。直接用数量排名会产生方向性错误。这是上线前必须解决的 P0。

## 4. 五项指标逐项审计与设计

### 4.1 竞品密度

**当前可用数据**

- `Poi.venue_category`、`venue_category_id`、`geom/latitude/longitude/venue_id`，见 `backend/app/models/poi.py::Poi`。
- 当前 `QueryPOITool` 能按单个精确类别 + bbox 取 POI，见 `backend/app/agent/tools/poi_tool.py::QueryPOITool.run()`。

**缺失数据**

- 没有项目级咖啡竞品 taxonomy；当前规则只认 `Coffee Shop`，数据中另有 `Café`。
- 没有可靠品牌名、连锁归属、门店面积、座位、价格带、开闭店状态、评分或营业时间。
- 没有真实商圈 Polygon 和面积版本。

**可行计算方法**

1. 对版本化候选 Polygon 做 `ST_Covers(area, Poi.geom)`；边界点口径必须固定，避免 `ST_Within` 排除边界点。
2. `raw_value = COUNT(DISTINCT venue_id) / ST_Area(area::geography) * 1,000,000`，单位为“竞品 POI/km²”。
3. 同时返回 `competitor_count`、`area_km2`、按类别拆分；不要只返回分数。
4. 若综合分中把竞争作为压力，则 `direction=lower_is_better`；归一化后反向。若产品想表达“咖啡需求成熟度”，必须另立指标，不能悄悄改变方向。

**所需 Repository 查询**

- 新增 `site_selection_repository.count_pois_by_areas_and_categories(area_geometries, category_ids)`：数据库内聚合，不走 `query_by_bbox()` 的 2,000 条上限。
- 新增 `site_selection_repository.list_pois_by_area(..., limit)`：只为地图抽样/点图层，统计与展示查询分离。

**所需 Service**

- `SiteSelectionService._calculate_competition()`：读取配置中的竞品类别、计算面积与密度、应用方向和归一化、保留 breakdown。

**建议返回结构**

```json
{
  "key": "competition_density",
  "label": "竞品密度",
  "raw_value": 100.0,
  "raw_unit": "poi_per_km2",
  "normalized_score": 0,
  "direction": "lower_is_better",
  "weight": null,
  "breakdown": {"competitor_count": 201, "area_km2": 2.009, "by_category": {}},
  "data_source": ["pois.venue_category", "pois.geom"]
}
```

`normalized_score/weight` 由尚未存在的版本化配置产生，上例字段只表达结构，不代表当前真实得分。

**技术风险**

- P0：类别口径、边界和指标方向不定会直接改变排名。
- P1：Foursquare POI 是历史样本，不能证明当前门店仍营业；同 venue 坐标/类别存在变体。
- P1：`query_by_bbox()` 返回上限会截断新宿/银座全 POI，禁止以 API 返回长度代替 SQL COUNT。

### 4.2 交通便利度

**当前可用数据**

- 数据中存在交通类 POI；`query_by_radius()` 已能以米计算 `ST_Distance`，见 `backend/app/repositories/poi_repository.py::query_by_radius()`。

**缺失数据**

- 无线路、换乘关系、站点出入口去重、服务频率、首末班、步行路网、旅行时间、无障碍、站点客流。

**可行计算方法**

- 只能命名为“交通 POI 可达性代理”。对候选区内及外扩 buffer 的交通类别做分类权重与距离衰减，例如 `sum(category_weight * exp(-distance_m/scale)) / area_km2`。
- 结果必须同时返回各类别数量、最近距离/距离分布和 buffer，不能把站点数量解释为乘客量。
- 多个站台/入口可能是同一枢纽；第一版可按 `venue_id` 去重并披露风险，不声称“车站数”。

**所需 Repository 查询**

- `aggregate_transport_accessibility(area_geometries, category_ids, buffer_m)`：区域/buffer 内按类别计数，并计算 POI 到区域几何的 `ST_Distance`。

**所需 Service**

- `SiteSelectionService._calculate_transport()`：应用版本化交通类别白名单、类别权重和距离衰减参数。

**建议返回结构**

```json
{
  "key": "transport_accessibility",
  "raw_value": 31.6,
  "raw_unit": "weighted_transport_poi_per_km2",
  "normalized_score": null,
  "direction": "higher_is_better",
  "breakdown": {"buffer_m": 800, "by_category": {}, "nearest_distance_m": null},
  "limitations": ["不包含站点客流、线路频率和步行路网"]
}
```

**技术风险**

- P0：若页面写“交通客流/日均乘客”，即构成虚假数据。
- P1：Foursquare 的 `Train Station` 可能包含站台/入口重复，简单计数会放大大型枢纽。
- P1：区域中心点距离对非规则大 Polygon 不稳定，应计算到区域边界/候选点或统一 buffer。

### 4.3 业态配套度

**当前可用数据**

- 247 个 `venue_category` 可做类别组合；`poi_service.get_categories()` 可用于口径探查。

**缺失数据**

- 没有“咖啡店正向配套类别”配置及权重，也没有办公人数、商业面积、营业时间、消费关联、店铺质量。

**可行计算方法**

- 配置互斥/可审计的配套组，例如办公、购物、餐饮、住宿、教育、文化休闲、便利服务；每组返回 POI/km²。
- 计算 `weighted_category_density`，可辅以组级 Shannon entropy 表示组合多样性；不能把全类别越多简单等同于越适合咖啡店。
- 配套分数和交通/竞品类别必须避免重复计分，尤其是 Mall、Train Station 等。

**所需 Repository 查询**

- `aggregate_poi_category_groups(area_geometries, category_group_map)`：按区域、类别/类别组聚合 distinct venue。

**所需 Service**

- `SiteSelectionService._calculate_business_mix()`：应用类别组、权重、密度和多样性公式，返回组级贡献。

**建议返回结构**

```json
{
  "key": "business_mix",
  "raw_value": null,
  "raw_unit": "weighted_mix_index",
  "normalized_score": null,
  "direction": "higher_is_better",
  "breakdown": {"group_density": {}, "diversity": null, "excluded_overlap": []}
}
```

**技术风险**

- P0：没有领域配置时，“配套度”只是任意类别加权。
- P1：高密度酒吧/餐厅不一定对目标咖啡产品正向，需明确业务假设。
- P1：原始类别粒度不均，同一大类的子类数会影响多样性。

### 4.4 历史访问活跃度

**当前可用数据**

- `Checkin.user_id/venue_id/utc_timestamp/timezone_offset` 和 `Poi.geom`；原始数据时间范围已核验为 2012-04-03 至 2013-02-16。

**缺失数据**

- 无实际进店人数、停留时长、未签到访客、订单、实时或当前客流；用户不是东京人口抽样框。

**可行计算方法**

- 区域内聚合 `checkin_count`、`distinct_user_count`、`distinct_active_day_count`、`visited_poi_count`。
- 主 raw 指标可用 `checkins / area_km2 / active_day`，并把独立用户数作为覆盖校验；必须展示观测期。
- 若分析日内时段，使用 `utc_timestamp + timezone_offset` 恢复签到本地时间；不能假设所有记录都是固定 JST，因为原始 `timezoneOffset` 存在多个值。

**所需 Repository 查询**

- `aggregate_checkin_activity(area_geometries, start_time, end_time)`：`checkins JOIN pois` 后在数据库内按区域聚合。
- 可选 `activity_grid(...)`：按格网聚合 checkin count，为历史活动 heatmap 提供权重；不能复用当前只统计 POI 的 `query_density_grid()` 结果冒充活动热力。

**所需 Service**

- `SiteSelectionService._calculate_historical_activity()`：观测窗、面积/天数归一化、样本覆盖和风险说明。

**建议返回结构**

```json
{
  "key": "historical_visit_activity",
  "raw_value": null,
  "raw_unit": "checkins_per_km2_per_active_day",
  "normalized_score": null,
  "direction": "higher_is_better",
  "breakdown": {"checkins": 24921, "unique_users": 1665, "active_days": 249},
  "observation_period": {"start": "2012-04-03", "end": "2013-02-16"}
}
```

**技术风险**

- P0：页面必须写“历史 Foursquare 签到活跃度/历史签到代理”，禁止写“客流”。
- P1：空间面积、活跃天数和样本用户覆盖不归一化会使区域不可比。
- P1：数据距今多年，适合方法演示，不足以支撑当前开店决策。

### 4.5 历史区域流入强度

**当前可用数据**

- `Checkin.session_id/sequence_no/utc_timestamp`、相邻点 `venue_id` 和 `Poi.geom`；`session_points_TKY.csv` 中存在 532,290 个有序点。

**缺失数据**

- 无真实出行起讫、交通方式、路线、通勤目的、全量人流；24 小时切分并不等于一次 trip。

**可行计算方法**

1. 先在全量 session 点上用 `LAG()` 取得前一 POI，不能先过滤目标区，否则会丢失真实前序点。
2. 当 `current_area=A` 且 `previous_area!=A` 时计一次进入；首点无前序，不计。
3. 返回 `entry_transition_count`、`distinct_entry_sessions`、`distinct_entry_users`；主指标可按有效 session 数或面积归一化。
4. 地图流向线必须聚合到候选区/空间格网，返回 count/unique_users，不展示单用户轨迹，避免隐私和视觉过载。

**所需 Repository 查询**

- `aggregate_area_inflows(area_geometries, dataset, min_count)`：CTE + `LAG(Checkin.venue_id)`/`sequence_no`，连接前后 POI，分类 origin/destination，按区域或 origin grid 聚合。
- 查询必须校验 `sessions.checkin_count` 与实际点数，参考 `backend/migrations/20260714_data_quality_checks.sql` 的一致性思路。

**所需 Service**

- `SiteSelectionService._calculate_historical_inflow()`：选择分母、最小流量阈值、隐私聚合、生成 flow layer payload。

**建议返回结构**

```json
{
  "key": "historical_area_inflow",
  "raw_value": null,
  "raw_unit": "entry_transitions_per_1000_sessions",
  "normalized_score": null,
  "direction": "higher_is_better",
  "breakdown": {"entries": 9014, "entry_sessions": 6893, "entry_users": 1510},
  "limitations": ["24 小时 session 代理，不代表真实行程"]
}
```

**技术风险**

- P0：当前 `build_sessions.py` 不能重放数据库回填，实际 DB session 完整性未在线核验。
- P1：同一用户频繁签到会放大强度；需要同时给 unique users/sessions。
- P1：直接返回单条用户流线有隐私和性能风险，只允许聚合线。

### 4.6 综合评分、理由和风险的统一返回

建议 `SiteSelectionService.analyze()` 返回版本化、可审计的结构，而不是让 LLM自行算分：

```json
{
  "analysis_type": "tokyo_coffee_site_selection",
  "config_version": "required-but-not-yet-defined",
  "dataset": {"name": "TSMC2014-TKY", "observation_start": "2012-04-03", "observation_end": "2013-02-16"},
  "ranking_scope": "relative_to_selected_candidates",
  "candidates": [
    {
      "area_id": "shibuya",
      "area_name": "涩谷",
      "rank": null,
      "composite_score": null,
      "metrics": [],
      "reasons": [],
      "risks": []
    }
  ],
  "map_layers": [],
  "global_risks": ["历史签到样本偏差", "不含人口/租金/销售额/实时客流"]
}
```

- 五维原始值先按各自方向归一化到统一尺度，再按配置权重加权；权重之和必须为 1。
- 只有 3-4 个候选时，候选内 min-max 会强制制造 0/100 极值，P1 应优先使用固定阈值或历史基准；若 MVP 暂用候选内相对归一化，必须返回 `ranking_scope=relative_to_selected_candidates`。
- `reasons` 由最高正贡献和主要短板模板化生成，并引用具体 raw value；LLM只能润色，不得新增事实。
- `risks` 由数据/配置规则生成，例如 `OLD_DATA`、`BBOX_PROXY`、`CATEGORY_PROXY`、`LOW_SAMPLE`，不能让 LLM自由编造风险。

## 5. GeoResolver 对四个候选区域的支持

`backend/app/agent/geo/resolver.py::_PLACE_INDEX` 已包含四个候选区域的中文简体和英文小写别名，`GeoResolver.resolve()` 会 trim + lower：

| 区域 | 当前别名 | 当前 bbox | 单元测试 | 结论 |
|---|---|---|---|---|
| 涩谷 | `涩谷`、`shibuya` | 139.695/35.655/139.715/35.665 | `test_resolver_known_place_returns_bbox`、`test_resolver_english_alias` | 支持 |
| 新宿 | `新宿`、`shinjuku` | 139.695/35.685/139.715/35.705 | 无专门用例 | 代码支持、未测试 |
| 银座 | `银座`、`ginza` | 139.750/35.665/139.775/35.685 | 无专门用例 | 代码支持、未测试 |
| 池袋 | `池袋`、`ikebukuro` | 139.705/35.725/139.725/35.745 | 无专门用例 | 代码支持、未测试 |

P0/P1 问题：

- P0：这些是手写矩形，不是有来源、版本、面积的商圈 Polygon；面积相差约 2.5 倍。
- P0：`LLMIntentRouter._resolve_location()` 对未知地点静默回退 `DEFAULT_BBOX`。选址请求中拼写错误会分析错误区域而不是报错，必须对 `SiteSelectionTool` fail closed。
- P1：缺少日文常用别名 `渋谷`、`銀座`，也不支持“新宿站/涩谷站/新宿区”等组合名。
- P1：`backend/tests/test_agent_geo.py` 只锁定涩谷与东京默认框，没有覆盖新宿、银座、池袋以及选址场景禁止 fallback。

最小建议：保留 `GeoResolver.resolve()` 接口，但候选区域几何改从版本化 site-selection 配置读取；Resolver 只负责 alias → `area_id`，不再把商圈边界硬编码在 Python 字典里。

## 6. 当前 map_layers 支持审计

| 目标图层 | 当前后端协议 | 当前前端渲染 | 结论 |
|---|---|---|---|
| 商圈 Polygon | `MapLayer.type` 不含 polygon | 无 fill/line source/layer | 不支持（P0） |
| POI 点 | `type="poi"`，`build_map_layers()` 已生成 | `poiLayer.ts` + `useMap.addPoiLayer()` | 支持 |
| Heatmap | `type="heatmap"` | `heatmapLayer.ts` + `setDensityLayer()` | 渲染支持；当前后端只生成全 POI 密度，不是签到热力 |
| 区域流向线 | 只有 `trajectory` 单轨迹点序列 | `trajectoryLayer.ts` 只构造一条时序 LineString，固定样式/起终点 | 不支持聚合流向（P0） |
| 候选区域高亮 | 无 selected area/feature-state 协议 | 无 Polygon source，自然无法高亮 | 不支持（P0） |

协议限制证据：

- `backend/app/agent/schemas.py::MapLayer.type` 只有 `heatmap/poi/trajectory`，且 `data` 固定为 `list[dict]`。
- `frontend/src/types/agent.ts::AgentMapLayerType` 同样只有三类。
- `frontend/src/components/map/MapLayerRenderer.vue::applyLayers()` 只处理三类并先清空所有 source。
- `useMap` 使用固定 `POI_SOURCE_ID/TRAJECTORY_SOURCE_ID/HEATMAP_SOURCE_ID`。若同一响应有多个同类型层，循环中的后一次 `setData()` 会覆盖前一次；不同类型可同时存在，同类型不能独立开关/叠加。

最小扩展建议：

- MapLayer 增加稳定 `id`、`type` 至少扩为 `polygon/flow`，`data` 允许 GeoJSON FeatureCollection，`metadata` 携带 label/unit/config_version。
- 商圈边界和高亮共用一个 Polygon source，feature properties 包含 `area_id/rank/selected/composite_score`；无需为高亮再造业务数据类型。
- 新增 `polygonLayer.ts`（fill + outline）和 `flowLayer.ts`（聚合 LineString，宽度/透明度按 count）；不要拿 `trajectoryLayer.ts` 冒充流向层。
- POI/heatmap/flow 的数值含义写入 legend；“POI 密度 heatmap”和“历史签到活跃 heatmap”必须用不同 label。

## 7. 新增 SiteSelectionTool 的最小职责边界（设计，不写代码）

### 7.1 输入边界

- `city`：第一版只允许 `tokyo`。
- `business_type`：第一版只允许 `coffee_shop`。
- `candidate_area_ids`：默认配置中的 `shinjuku/shibuya/ginza`，可选加 `ikebukuro`；必须是 allowlist。
- `config_version`：可选但必须能回显；不允许 LLM传任意 Polygon、SQL、类别或权重。

### 7.2 Tool 只做四件事

1. 继承 `AgentTool` 并声明 Function Calling schema。
2. 验证固定城市/业态/候选区/配置版本；未知区域直接 `ValueError`，禁止回退东京默认 bbox。
3. 调用一次 `SiteSelectionService.analyze()`。
4. 原样返回结构化 `SiteSelectionResult`。

### 7.3 Tool 明确不负责

- 不写 SQL/PostGIS；SQL 只进 `site_selection_repository.py`，遵守 `AgentTool` 和现有 `poi_repository.py` 的边界。
- 不定义类别、Polygon、权重和归一化；全部来自版本化配置。
- 不在 Tool/LLM 中计算综合分。
- 不调用下一 POI `RecommendTool` 拼接“需求分”；`RecommendationResult.score` 不是选址分。
- 不生成 Mapbox 样式；由 `AgentService.build_map_layers()`/前端图层模块适配。
- 不自由生成理由/风险；Service 返回事实模板，LLM最多润色并保留数值和限制。

### 7.4 Agent 协议最小变化

现有 `ChatResponse` 会丢弃 Tool 的完整结构化结果。建议新增通用 `artifacts`（例如 `{type:"site_selection", data:...}`），并在同步响应和 SSE `done` 同步返回；排名卡片消费 artifact，地图消费 `map_layers`，自然语言消费 `reply`。涉及 `backend/app/agent/schemas.py::ChatResponse`、`AgentService._run_intent()/chat_stream()`、`frontend/src/types/agent.ts::AgentChatResponse`、`frontend/src/composables/useAgentWorkspace.ts::applyResponse()`。

## 8. 前端页面审计与第一版信息架构

### 8.1 第一版只应实现哪个页面

**第一版只改造 `/agent` 为“东京咖啡店选址工作台”。** 复用 `frontend/src/views/agent/AgentView.vue` 的 Agent + Map 双栏，但把通用 capability cards、示例问题和结果区收敛为：候选区选择/发问 → 排名表 → 五维指标 → 推荐理由/风险 → 地图图层。

理由：该页面已经通过 `AgentWorkspace`、`useAgentWorkspace`、`MapLayerRenderer` 形成端到端主链路；新增独立 Dashboard、独立 SiteSelection 页面或多个业务页只会重复状态和接口。

### 8.2 页面去留

| 路由/文件 | 建议 | 依据 |
|---|---|---|
| `/agent` `views/agent/AgentView.vue` | **唯一 MVP 页面，重点改造** | 已有 Agent + 地图工作区 |
| `/dashboard` `views/dashboard/Dashboard.vue` | 降级到模型中心/内部入口 | 主要消费 `metrics.json`，`RecommendationPipeline.vue` 是静态模型链路 |
| `/recommendation` `RecommendationView.vue` | 降级到模型中心 | 展示下一 POI `rank/score/target`，不是商圈选址 |
| `/model-analysis` `ModelAnalysis.vue` | 保留代码，归模型中心且默认隐藏 | 当前已在 `AppShell.vue` 标记 `hidden:true` |
| `/trajectory` `TrajectoryView.vue` | 归数据/模型中心 | 用于单用户 session 质检，不是选址主流程 |
| `/poi-map` `PoiMap.vue` | 保留为内部数据探索 | 可做 POI 数据 QA；当前一次最多渲染 `RENDER_LIMIT`，不提供选址排名 |
| `/spatial` `SpatialAnalysisView.vue` | 保留为内部能力实验页 | 当前文案明确是 Stage 2 密度能力验证，且只分析全 POI |

`frontend/src/components/common/AppShell.vue::menuItems` 当前仍公开 Agent、Dashboard、POI、轨迹、推荐五个入口；MVP 对外导航应只突出选址工作台，其余统一进“模型与数据中心”，避免用户把下一 POI 推荐页误解为选址结果。

### 8.3 `/agent` 必改内容

- `PromptInput.vue`、`ExamplePrompts.vue`、`CapabilitySection.vue` 当前仍宣传通用 POI/热力/地点推荐/轨迹；应改为固定东京、咖啡业态和候选区场景。
- 新增结构化结果组件（排名 + 五维指标 + raw value/unit + 综合分 + reasons + risks），消费 `artifacts`，不能从 Agent 文本反解析。
- `MapLegend.vue/MapStatusBar.vue` 增加 Polygon、历史活动 heatmap、聚合流向、候选高亮语义。
- 所有页面常驻展示数据观测期与“历史 Foursquare 签到代理”免责声明。

## 9. 数据库新增表还是仅新增配置

### 9.1 MVP 建议

**不新增业务数据表，新增一份版本化配置即可。** 配置至少包含：

- `city/business_type/config_version`；
- 四个候选区的 `area_id/name/aliases/GeoJSON Polygon/provenance`；
- 竞品、交通、配套类别 ID/名称白名单和排除项；
- 五项指标公式参数、方向、权重、归一化阈值；
- heatmap grid/buffer/flow 最小聚合阈值；
- 数据集名称、观测期和强制风险文案。

配置适合放在后端版本控制内并由 Service 读取；不能散落到 `GeoResolver._PLACE_INDEX`、前端常量和 prompt 三处。

### 9.2 必须补的数据库工程项（不是新业务表）

- P0：验证实际 `pois.geom` GIST 索引存在，并补可重放迁移；仓库当前没有初始 DDL。
- P0：补 sessions/checkins 回填的可重放流程，并运行 `backend/migrations/20260714_data_quality_checks.sql` 类校验。
- P1：用 `EXPLAIN ANALYZE` 验证 `checkins(venue_id)`、`checkins(session_id,sequence_no)`、`pois(venue_category)`、`pois.geom` 对五类聚合的执行计划。
- P2：只有当计算延迟不能接受时，再引入物化视图/日聚合表；第一版数据量（约 57 万 checkins、6.2 万 POI）没有理由先造复杂表。
- P2：若未来要保存用户发起的分析版本、审计快照和人工备注，再新增 `site_selection_runs`；它不是首版计算前置条件。

## 10. 问题优先级

### P0：没有解决就不能发布选址 MVP

1. **选址领域链路缺失**：没有 `SiteSelectionRepository/Service/Schema/Tool` 和结构化 artifact；当前四个 Tool 不能输出候选区五维排名。证据见 `build_default_registry()` 和 `ChatResponse`。
2. **区域边界不可比**：`GeoResolver._PLACE_INDEX` 是面积不等、无来源的 bbox，不是商圈 Polygon。
3. **统计口径未定义**：咖啡竞品 taxonomy、交通/配套白名单、五项方向、权重、归一化和版本均不存在。
4. **Repository 能力不足**：现有 `query_by_bbox()` 有 limit，`query_density_grid()` 无类别/checkin/flow；不能安全计算五项全量聚合。
5. **地图协议不足**：`MapLayer`/`AgentMapLayerType` 不支持 Polygon、flow、highlight。
6. **session 持久化不可重放**：`build_sessions.py` 只导出 CSV，与文档宣称的 DB 回填不一致；历史流入依赖此链路。
7. **错误区域静默回退**：选址场景必须禁止 `LLMIntentRouter._resolve_location()` 的未知地点 → `DEFAULT_BBOX`。
8. **数据口径披露**：所有选址页面必须标明 2012-2013 历史 Foursquare 样本，禁止写成当前/实时商业指标。
9. **安全凭据**：`backend/app/core/config.py::Settings.llm_api_key` 存在源码内非空默认密钥，`Utils/seperate.py::DB_CONFIG` 也硬编码数据库凭据。必须撤销/轮换并只从环境注入；本报告不复述任何密钥值。

### P1：MVP 可信度与稳定性

1. 对 `Coffee Shop/Café`、交通站点重复、配套类别交叉计分做数据词典和 QA。
2. 处理原始数据中 venue 坐标/类别变体，并说明 `drop_duplicates` 的选择策略。
3. 增加固定基准归一化；若先用候选内相对分，显式披露小样本排名不稳定。
4. 聚合流向到区域/格网并设置最小 count/unique-user 阈值。
5. 同类型多个地图层使用独立 layer/source id，避免 `setData` 覆盖。
6. 把通用页面归入模型与数据中心；只保留选址主流程的产品导航。
7. 修正文档漂移：`backend/README.md` 仍称 trajectory 为 CSV mock；`docs/user-trajectory-database-integration.md` 的 session 规则/写库/Cesium 描述与当前代码不一致；`docs/poi-display-name-integration.md` 仍描述已移除的兼容字段。
8. 补齐后端依赖环境、运行 78 个既有测试并增加前端自动化测试。当前 78 个测试函数来自 `backend/tests/`，本次环境因缺 `psycopg` 未能收集。

### P2：后续增强

1. 真实地理编码/商圈边界服务、多城市/多业态配置管理。
2. 物化日聚合、缓存、离线计算和 `site_selection_runs` 审计表。
3. 引入新的真实开放数据后再扩展客流、租金、人口等指标；在接入前不得预留假值。
4. 面向品牌/店铺实体解析、站点入口聚合、步行路网可达性。

## 11. 按文件划分的最小改造清单（仅设计）

### 后端新增

| 文件 | 最小职责 |
|---|---|
| `backend/app/repositories/site_selection_repository.py` | 五类数据库聚合：POI 类别、交通距离、配套组、checkin 活跃、session inflow |
| `backend/app/services/site_selection_service.py` | 读取配置、编排查询、归一化/加权、生成事实理由/风险和 map payload |
| `backend/app/schemas/site_selection.py` | Candidate、Metric、Ranking、Risk、Artifact 的严格响应模型 |
| `backend/app/agent/tools/site_selection_tool.py` | 允许列表参数校验 + 调用 Service，不写 SQL/公式 |
| `backend/app/site_selection/config/tokyo_coffee.json` | Polygon、aliases、分类、方向、权重、阈值、数据披露、版本 |
| `backend/tests/test_site_selection_repository.py` | 五类聚合集成测试 |
| `backend/tests/test_site_selection_service.py` | 分数、排名、理由、风险、配置测试 |
| `backend/tests/test_site_selection_tool.py` | Tool/Agent/SSE/未知区域 fail-closed 测试 |

### 后端修改

| 文件 | 最小修改 |
|---|---|
| `backend/app/agent/service.py` | 注册 `SiteSelectionTool`；构建选址 map_layers/artifact/reply |
| `backend/app/agent/schemas.py` | 增加 artifact；扩展 map layer 类型/GeoJSON data 契约 |
| `backend/app/agent/router_llm.py` | 把 site selection 纳入 Tool schema；选址区域不走 bbox 静默 fallback |
| `backend/app/agent/prompts/prompt.py` | 系统提示和降级规则收敛为东京咖啡选址；不在 prompt 写权重/事实 |
| `backend/app/agent/geo/resolver.py` | alias → area_id；边界从版本化配置读取 |
| `backend/app/agent/stream.py` | `done`/summary 支持 site-selection artifact 摘要 |
| `backend/scripts/build_sessions.py` | 未来实施时补可重放 DB 写入/回填模式；保持事务与 dry-run |
| `backend/migrations/*` | 补完整空间索引/session 回填相关迁移或校验，不必新增选址业务表 |
| `backend/app/core/config.py`、`Utils/seperate.py` | 移除/轮换硬编码凭据，仅环境注入（安全 P0） |

### 前端新增

| 文件 | 最小职责 |
|---|---|
| `frontend/src/types/siteSelection.ts` | 与后端 artifact/metric/risk 对齐 |
| `frontend/src/components/site-selection/SiteSelectionResult.vue` | 排名、综合分、五维 raw/score/unit、理由、风险、观测期 |
| `frontend/src/map/layers/polygonLayer.ts` | 商圈 fill/outline/selected 高亮 |
| `frontend/src/map/layers/flowLayer.ts` | 聚合流向 LineString/宽度/透明度/点击信息 |

### 前端修改

| 文件 | 最小修改 |
|---|---|
| `frontend/src/types/agent.ts` | map layer 新类型 + artifact |
| `frontend/src/composables/useAgentWorkspace.ts` | 保存/清空 artifact |
| `frontend/src/components/agent/AgentWorkspace.vue` | 展示选址结果组件 |
| `frontend/src/components/agent/PromptInput.vue`、`ExamplePrompts.vue`、`CapabilitySection.vue` | 收敛为东京咖啡选址 |
| `frontend/src/components/map/MapLayerRenderer.vue` | 分派 polygon/flow/highlight，避免同类 source 覆盖 |
| `frontend/src/components/map/MapContainer.vue`、`frontend/src/composables/useMap.ts` | expose Polygon/flow 更新与候选 fit/highlight |
| `frontend/src/components/map/MapLegend.vue`、`MapStatusBar.vue` | 新图层语义、指标单位、数据期 |
| `frontend/src/views/agent/AgentView.vue` | 唯一选址工作台布局 |
| `frontend/src/components/common/AppShell.vue`、`frontend/src/router/index.ts` | 产品导航只突出选址；其他页归模型/数据中心 |

文档同步至少更新 `README.md`、`backend/README.md`，并把本审计定义的“代理指标/禁止指标”写进产品文案验收标准。

## 12. 测试清单

### 12.1 数据与 Repository

- 候选 Polygon 合法、闭合、SRID=4326、面积大于 0；边界点按 `ST_Covers` 计入。
- 四区竞品分类别 count、distinct venue、km² 密度与独立 SQL 基准一致；结果不受 API limit 影响。
- 交通白名单只计配置类别；`Gas Station / Garage` 等含“Station”字符串但不在白名单的类别不得误计。
- 配套类别组互斥/重复项校验，组级 count 与总贡献守恒。
- 活跃度返回 checkins/users/days/POIs，观测期正确，空区域返回 0 而不是 NaN。
- inflow：首点不计、同区连续不计、外区→目标计、候选区→候选区计；必须先 LAG 后区域过滤。
- 同一 timestamp 时按 `sequence_no`、`utc_timestamp`、`id` 的稳定顺序；session 缺失点/孤立点有明确处理。
- 流向结果满足最小 count/unique-user 阈值，不泄漏 user_id/session_id。
- 运行 users/checkins/pois/session 关联完整性和 `sessions.checkin_count` 一致性检查。
- `EXPLAIN ANALYZE` 锁定五类查询的最大响应时间和索引使用。

### 12.2 Service 与评分

- 配置 schema：城市/业态/area/taxonomy/方向/权重/阈值/版本必填，权重和为 1。
- 每项 raw value/unit/breakdown/data_source/observation_period 完整。
- lower-is-better 只对竞品压力反向；其余方向按配置。
- 零方差、缺失、空样本、极值、3 区/4 区、并列分数稳定处理；tie-break 规则固定。
- composite score 等于五项 contribution 之和，不由 LLM二次计算。
- reasons 只引用实际指标，risks 必含历史期/样本偏差/禁用数据提醒。
- 同输入 + 同 config_version 返回确定性结果。

### 12.3 Tool、Agent 与 API

- `SiteSelectionTool` schema 只允许东京/咖啡/allowlist areas；未知 area、任意 Polygon、任意权重被拒绝。
- `build_default_registry()` 注册工具后，原“恰好 4 个工具”测试（`test_agent_llm_api.py::test_router_tools_schema_is_function_format`）同步改为语义断言。
- 中文/英文/日文 alias 覆盖四区；选址请求未知地点不 fallback。
- 同步 `/api/agent/chat` 和 SSE `done` 的 artifact/map_layers 一致。
- Tool 结果摘要不携带全量明细；错误事件保持可读。
- 既有 query_poi/spatial_density/recommend/track 和 78 个后端测试全部回归。

### 12.4 前端与地图

- 为前端引入测试框架后，覆盖 artifact 类型解析、五维/单位/空值/风险渲染。
- Polygon fill/outline、selected 高亮、POI、历史活动 heatmap、flow 可同时显示。
- 多个同类型 layer 不互相覆盖；开关、清空、重新分析不残留旧 source。
- flow 宽度按 count、tooltip 使用聚合值，不显示用户/session。
- 点击排名候选区联动地图，高亮与表格 rank 一致。
- 缺 Mapbox token、空数据、非法 GeoJSON、网络/SSE 中断有降级态。
- 页面始终可见观测期和代理指标免责声明；移动端不隐藏风险说明。
- `npm run lint`、`npm run build`、浏览器 E2E 场景全部通过。

### 12.5 验收场景

1. “比较新宿、涩谷和银座开咖啡店，加入池袋”返回 4 区相对排名、五维 raw/score、综合分、理由、风险和全部地图层。
2. 关闭池袋后重新归一化，响应明确标注 `ranking_scope`，不把两次相对分当绝对分比较。
3. “比较大阪”或拼错区域返回受控错误，不悄悄分析东京默认框。
4. 用户询问租金、实时客流或销售额时，Agent 明确说明无数据，不返回数值。

## 13. 当前无法由真实数据支撑、禁止在页面展示的指标

以下指标在引入可追溯真实数据源前一律禁止展示数值、等级、趋势、预测或“AI 估算”：

1. **人口/客群**：常住人口、白天人口、办公人口、年龄、收入、职业、游客比例、消费能力。`User` 只有匿名 `user_id`。
2. **销售经营**：营业额、订单量、客单价、转化率、复购率、利润、毛利、ROI、回本周期、盈亏平衡点、销量预测。
3. **客流**：实时客流、当前客流、街道人流、进店人数、停留时长、日均顾客、站点客流。`Checkin` 只能支持“历史 Foursquare 签到数/匿名签到用户数”。
4. **租赁地产**：真实租金、铺面价格、空置率、可租铺位、面积、物业条件、转让费、合同条款。
5. **交通真实服务**：线路覆盖、班次、换乘时间、旅行时间、步行时间、拥堵、停车位、站点日均乘客；当前只能展示交通类 POI 计数/距离代理。
6. **竞品经营**：竞品品牌/连锁归属、门店规模、座位数、价格、销量、评分、口碑、营业时间、开闭店状态、市场份额、同品牌蚕食。原始 TKY 无真实名称字段。
7. **需求/市场**：商圈容量、潜在顾客数、市场需求、购买意愿、消费热度、增长率、供需缺口、白地机会。
8. **区域现实属性**：行政/商业官方边界、用地/分区、犯罪、安全、天气、活动、旅游统计、办公/商场建筑面积；内置 bbox 不能冒充官方商圈 Polygon。
9. **真实流动**：通勤流、OD 人次、交通方式、来源人口、到访目的、路线；只能展示“历史 24 小时 session 内相邻签到进入代理”。
10. **当前趋势**：同比/环比、近月增长、疫情后恢复、当前热门区域。数据观测期是 2012-2013。
11. **选址概率**：成功概率、开店成功率、倒闭风险、收入置信区间。
12. **把模型输出改名为商业指标**：`RecommendationResult.score` 不能显示为商圈适宜度、到访概率或需求分；`metrics.json` 的 HR/NDCG/MRR 只能留在模型中心。证据见 `backend/app/models/recommendation_result.py`、`backend/app/services/metrics_service.py`、`backend/app/data/metrics.json`。

允许展示的措辞必须准确：

- “历史签到数/历史匿名签到用户数”，不写“客流/顾客数”。
- “交通 POI 可达性代理”，不写“交通客流/通勤便利指数”（除非解释公式）。
- “历史签到序列区域进入代理”，不写“区域真实流入人口”。
- “候选集合内相对综合分”，不写“绝对开店成功指数”。

## 14. 最小可行实施路径

1. **先锁定数据契约（P0）**：版本化四个候选 Polygon、分类白名单、五项方向/权重/归一化、观测期和禁用措辞；选址区域解析 fail closed。
2. **补数据可重放性（P0）**：把 session 构建/回填与 geom/GIST 迁移变成可重放流程，跑完整质量检查；在依赖就绪环境运行现有 78 个测试。
3. **实现一个垂直后端切片（P0）**：`site_selection_repository → SiteSelectionService → SiteSelectionTool → ChatResponse artifact/map_layers`，只支持 Tokyo/Coffee/3+1 区。
4. **实现地图缺口（P0）**：Polygon/selected、签到 activity heatmap、聚合 flow；保留现有 POI layer。
5. **只改造 `/agent`（P0/P1）**：结构化排名/五维/理由/风险与地图联动；其他页面归模型/数据中心。
6. **用固定 fixtures 和真实制品抽样验收（P1）**：锁定 raw values、单位、排名确定性、性能和禁止指标拒答。

完成上述路径后，项目可以作为**“用历史开放空间与签到数据对东京候选商圈做相对比较的咖啡店选址 Agent MVP”**发布。若仍使用当前 bbox、未定义 taxonomy/权重、把历史签到称为客流，或展示人口/租金/销售额等缺失数据，则不应发布为零售选址 MVP。
