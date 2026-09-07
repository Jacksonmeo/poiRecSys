# Agent 修改日志 — 前端

本文档记录 Claude Code Agent 对前端代码的所有修改。

---

## 2026-07-15：Stage 6 — Agentic GIS 重构（产品收敛为 Agent + 地图）

### 修改概述

删除与 Agent/地图无关的页面与模块：Dashboard、模型实验（ModelAnalysis /
RecommendationView）、推荐/指标 API 封装、图表组件、相关 composables 与类型；
路由收敛为工作台 + 3 个地图探索页；移除 echarts 依赖。

### 修改文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/views/dashboard/` | 删除 | Legacy Dashboard 页面组 |
| `src/views/ModelAnalysis.vue` | 删除 | 模型实验分析页 |
| `src/views/RecommendationView.vue` | 删除 | 推荐实验页 |
| `src/views/agent/AgentView.vue` | 删除 | 死代码（无路由引用，/agent 重定向到工作台） |
| `src/components/charts/` | 删除 | ECharts 图表组件（echarts 依赖一并移除） |
| `src/components/cards/MetricCard.vue` | 删除 | Dashboard 指标卡 |
| `src/components/recommendation/` | 删除 | 推荐卡片组件组 |
| `src/composables/useDashboardMetrics.ts` | 删除 | Dashboard 指标流 |
| `src/composables/useRecommendationExplanation.ts` | 删除 | 推荐解释（随推荐页移除） |
| `src/utils/modelMetrics.ts` / `src/types/model.ts` | 删除 | 模型指标工具与类型 |
| `src/api/metrics.ts` / `src/api/recommend.ts` | 删除 | 对应 API 封装 |
| `src/styles/dashboard-hero.css` | 删除 | Dashboard 样式 |
| `src/router/index.ts` | 修改 | 移除 dashboard / model-lab 路由，保留工作台 + 3 个地图页 |
| `src/components/common/AppShell.vue` | 修改 | 导航移除「模型实验」，新增「空间分析」入口 |
| `src/types/index.ts` | 修剪 | 移除推荐/模型指标相关类型 |
| `package.json` | 修改 | 移除 echarts 依赖 |

---

## 2026-07-11：POI 后端数据库迁移 — 前端适配说明

### 修改概述

后端 POI 数据源从 CSV 迁移到 PostgreSQL，前端通过后端 Schema 的向后兼容字段无需修改即可继续使用。

### 前端无需修改的文件

以下文件依赖 POI 数据的 `lng`、`lat`、`name`、`category` 字段，后端通过 Pydantic `computed_field` 自动提供这些兼容字段：

| 文件 | 依赖的 POI 字段 | 兼容状态 |
|------|----------------|---------|
| `src/api/poi.ts` | `Poi[]` 类型 | ✅ 兼容 — 字段名不变 |
| `src/types/index.ts` | `Poi` 接口 | ⚠️ 建议后续更新字段名为 DB 原生名 |
| `src/views/PoiMap.vue` | `lng`, `lat`, `name`, `category` | ✅ 兼容 — 自动取 computed 字段 |
| `src/components/CesiumMap.vue` | `lng`, `lat`, `name`, `category` | ✅ 兼容 — 自动取 computed 字段 |

### 字段映射关系

| 前端期望字段 | 后端实际字段 | 映射方式 | 备注 |
|-------------|-------------|---------|------|
| `poi_id` | `venue_id` | computed_field | 值为 Foursquare venue ID |
| `name` | `venue_id` | computed_field | ⚠️ 值为 venue_id（DB 无独立 name 列） |
| `category` | `venue_category` | computed_field | 直接映射 |
| `lng` | `longitude` | computed_field | 直接映射 |
| `lat` | `latitude` | computed_field | 直接映射 |
| `address` | — | computed_field（空字符串） | DB 无 address 列 |

### 响应新增字段

后端现在也返回数据库原生字段，前端可根据需要渐进式采用：

```json
{
  "id": 1,
  "venue_id": "4f0fd5a8e4b03856eeb6c8cb",
  "venue_category_id": "4bf58dd8d48988d10c951735",
  "venue_category": "Cosmetics Shop",
  "latitude": 35.70510109,
  "longitude": 139.61959
}
```

### 已知问题

1. **POI 名称显示**：目前 `name` 字段返回 `venue_id`（Foursquare ID），地图标注会显示类似 `4f0fd5a8e4b03856eeb6c8cb` 的字符串。如果后续数据库新增 `name` 列并填充数据，`computed_field` 的 `name` 属性可改为读取新列。

2. **推荐/轨迹模块 POI 引用**：`RecommendationView.vue` 和 `TrajectoryView.vue` 仍使用 CSV 数据（对应模块未迁移），POI ID 格式为 `poi_001`，与数据库 `venue_id` 不同。

### 推荐后续优化

1. 更新 `src/types/index.ts` 中的 `Poi` 接口使用数据库原生字段名
2. 在 `venue_category` 基础上新增 `name` 列以改善地图标注显示
3. 迁移 recommend 和 trajectory 模块到数据库

---

## 2026-07-11：display_name 前端贯通（类型 → 工具函数 → 组件）

### 修改概述

将数据库 `display_name` 字段贯通到前端所有 POI 展示位置。

### 修改文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/types/index.ts` | 修改 | Poi 接口新增 `id`, `venue_id`, `display_name`, `latitude`, `longitude` 等 DB 原生字段 |
| `src/utils/poi.ts` | 新建 | `getPoiDisplayName()` + `getPoiShortId()` 统一展示名称逻辑 |
| `src/components/CesiumMap.vue` | 修改 | 导入工具函数，label/description 使用 `getPoiDisplayName`；默认隐藏标签（推荐候选除外） |
| `src/views/RecommendationView.vue` | 修改 | 表格 POI 列和真实目标名称使用 `getPoiDisplayName` |

### 关键变更

1. **`PoiLike` 接口**：同时兼容新数据库 POI（`venue_id`, `display_name`, `venue_category`）和旧 CSV POI（`name`, `poi_id`, `category`）
2. **`getPoiDisplayName()` 优先级**：
   1. `display_name`（数据库填充）
   2. `name`（CSV 旧字段）
   3. `{category} · {shortId}`（兜底组合）
   4. 短 ID / 类别 / 'POI'（最终兜底）
3. **CesiumMap 标签**：
   - POI 地图页：默认不显示永久标签（`show: false`）
   - 推荐候选（有 `rank`）：保留排名标签
   - 点击 POI 时通过 infoBox 查看详情（含完整 `venue_id`）
4. **RecommendationView 表格**：候选 POI 列和真实目标行改用 `getPoiDisplayName`

### 不再使用 venue_id 长字符串作为主名称

修改前：地图标签直接显示完整 `4f0fd5a8e4b03856eeb6c8cb`
修改后：地图标签显示 `Coffee Shop · b6c8cb`（兜底）或数据库中的 `display_name`

完整 `venue_id` 仅在 Cesium infoBox 的 `<small>` 中展示，作为辅助参考。
## 2026-07-15：全量推荐结果分页展示

### 修改概述

推荐结果页面接入数据库版推荐 API。由于全量结果包含 46,402 个 session，列表改为
服务端分页读取，并增加用户 ID 筛选、session 选择、空状态和错误提示。

### 修改文件

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/views/RecommendationView.vue` | 修改 | 重构推荐页；分页选择 session，展示 Top-10、真实目标和 Cesium 轨迹/候选图层；增加中文模块注释 |
| `src/api/recommend.ts` | 修改 | 推荐列表接口增加 `skip/limit/user_id` 参数 |
| `src/types/index.ts` | 修改 | 新增 `RecommendationListResponse` 分页类型 |

### 页面数据流

1. 页面按 50 条一页请求推荐摘要。
2. 可输入用户 ID 过滤该用户的推荐 session。
3. 选择 session 后请求详情。
4. Cesium 地图绘制不含真实目标的历史轨迹、Top-10 候选和真实目标点。
5. 右侧表格显示候选 POI、rank 和 T10e-2 最终分数。

### 验证

- `vue-tsc -b` 通过
- Vite 生产构建通过
- 本地前端 `/recommendation` 返回 HTTP 200
- 本地后端推荐列表返回总数 46,402
- 当前环境未提供内嵌浏览器实例，因此未完成页面点击和截图验证

---
