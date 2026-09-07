# GeoAgent Stage 5.5 UI 产品化升级报告

## 1. 升级目标

本次升级仅调整 Frontend UX/Product 表达，不修改后端接口、SSE 协议、Agent/Tool 逻辑或数据库。

产品定位从“GIS 后台管理系统”迁移为“AI Spatial Intelligence Workspace”。核心交互叙事统一为：

> 用户提出空间问题 → Agent 理解任务 → 调用工具 → 执行空间分析或推荐 → 地图呈现结果图层

地图不再作为聊天框旁的背景，而是 Agent 任务的结果画布；对话区不再模拟客服聊天，而是展示可追踪的 AI 任务执行过程。

## 2. 基线检查

升级前首先执行：

```text
npm.cmd run lint
npm.cmd run build
```

基线结果均通过，没有发现 TypeScript 或 ESLint 阻塞错误。Vite 仅报告既有的大 chunk 警告，不影响构建产物生成。

## 3. 信息架构调整

| 区域 | 调整前 | Stage 5.5 |
| --- | --- | --- |
| Sidebar | 传统后台导航，视觉占比较高 | 收敛到约 216px，为 Agent 与地图让出主空间 |
| Agent Panel | 普通聊天空态和消息气泡 | Agent Workspace：能力入口、Prompt Cards、任务时间线、大尺寸输入框 |
| Conversation | 用户/助手文本消息 | 用户问题、任务理解、Tool 执行、参数 chips、图层生成、分析结论 |
| Map | 地图容器与基础图层 | Map Canvas：状态、空闲/执行态、图例、Insight、Top-1 推荐联动 |
| Recommendation | 紧凑结果条目 | Candidate Cards：Rank、名称、Score、Reason、地图定位 |

Agent Panel 与 Map Canvas 已合并为一个连续工作区边框，使用轻量分隔线而不是两张互不相关的卡片，弱化“三栏割裂感”。Agent Panel 默认宽度保持约 456px，可拖拽调整。

## 4. 新增组件

### Agent Workspace

- `frontend/src/components/agent/AgentWorkspace.vue`
  - Agent 工作台组合入口。
  - 只负责组合 Header、能力区、Prompt Cards、时间线和输入框。
- `frontend/src/components/agent/CapabilitySection.vue`
  - 展示 POI 查询、空间分析、下一地点推荐和轨迹分析四项能力。
  - 点击能力会发送可执行的自然语言任务，而非发送抽象功能名称。
- `frontend/src/components/agent/ConversationTimeline.vue`
  - 把用户问题、Agent 执行过程与分析结论组织成任务时间线。
- `frontend/src/components/agent/ToolTimeline.vue`
  - 展示 `pending / running / success / error` 四种状态。
  - Tool 参数通过 chips 展示，不暴露 JSON。

### Map Canvas

- `frontend/src/components/map/MapInsightCard.vue`
  - 展示真实 POI/推荐结果的 Top 3。
  - 点击条目调用既有 `flyToPoint` 定位地图。
- `frontend/src/components/map/MapRecommendationCard.vue`
  - 仅在存在真实 rank、score 的 Top-1 推荐候选时展示。
  - 展示后端 RecommendTool 返回的真实 reason，不生成模拟解释。

### 状态编排

- `frontend/src/composables/useAgentWorkspace.ts`
  - 从展示组件中抽离 session、SSE、非流式回退、消息与任务状态管理。
  - 复用现有 `/agent/chat` 和 `/agent/chat/stream`，没有改变协议。

### 独立样式

- `frontend/src/styles/app-shell.css`
- `frontend/src/styles/dashboard-hero.css`

上述样式从 Vue SFC 中机械抽离，使所有 Vue 组件保持在 300 行以内。

## 5. 修改文件

### Agent

- `frontend/src/components/agent/AgentPanelHeader.vue`
- `frontend/src/components/agent/ExamplePrompts.vue`
- `frontend/src/components/agent/PromptInput.vue`
- `frontend/src/composables/useToolExecution.ts`
- `frontend/src/views/agent/AgentView.vue`
- `frontend/src/types/agent.ts`
- `frontend/src/api/agent.ts`

### Map

- `frontend/src/components/map/MapLayerRenderer.vue`
- `frontend/src/components/map/MapStatusBar.vue`
- `frontend/src/components/map/MapLegend.vue`
- `frontend/src/map/layers/heatmapLayer.ts`
- `frontend/src/map/layers/poiLayer.ts`
- `frontend/src/map/layers/trajectoryLayer.ts`
- `frontend/src/types/map.ts`

`MapContainer` 生命周期与 `useMap` 核心调用方式保持不变。本轮地图调整集中在 renderer、overlay components 与 layer style。

### Recommendation

- `frontend/src/components/recommendation/RecommendationCard.vue`
- `frontend/src/components/recommendation/RecommendationResultCard.vue`
- `frontend/src/views/RecommendationView.vue`
- `frontend/src/composables/useRecommendationExplanation.ts`

### App Shell / Dashboard

- `frontend/src/components/common/AppShell.vue`
- `frontend/src/views/dashboard/DashboardHero.vue`
- `frontend/src/styles/app-shell.css`
- `frontend/src/styles/dashboard-hero.css`

## 6. 移除或替代的旧组件

- `AgentChat.vue` → 由 `AgentWorkspace.vue` 与 `useAgentWorkspace.ts` 替代。
- `MessageList.vue` → 由 `ConversationTimeline.vue` 替代。
- `ToolExecutionState.vue` → 由不暴露 JSON 的 `ToolTimeline.vue` 替代。

## 7. Bug 修复

### 7.1 SSE 结果类型不完整

`tool_result` 不只有 `count`，推荐与轨迹工具还会返回 `session_id`。前端 handler 已从 `{ count: number }` 调整为 `Record<string, unknown>`，与现有 SSE 实际载荷一致。

### 7.2 SSE 异常结束导致状态永久 pending

新增 `done` 事件完成标记。如果流提前结束且没有收到 `done`，前端会进入既有非流式回退流程，避免时间线永久停留在等待状态。

### 7.3 Tool 状态更新目标不稳定

Tool 成功事件现在从后向前寻找最近一条 running 记录，避免未来存在多条执行记录时错误更新较早任务。

### 7.4 原始 JSON 泄漏到产品界面

删除“查看参数”和 `<pre>` JSON 展示。bbox、grid size、category、Top-K、user/session 等参数均转换为可读 chips。

### 7.5 推荐浮层生成模拟分数

移除缺失分数时使用 `0.92 / 0.87` 等模拟值的逻辑。普通 POI 只显示定位操作；Recommendation Card 仅消费真实 score。

### 7.6 undefined 字段与地图定位保护

- Recommendation Card 只在真实 `rank === 1` 且 `score` 为 number 时展示。
- reason、score、经纬度均使用可选字段保护。
- 地图 flyTo 前检查经纬度是否为有限数值。

### 7.7 壳层重叠和短视口溢出

App Shell 使用明确的纵向 flex 约束；顶栏、主内容、侧栏菜单和账号区拥有稳定尺寸与滚动边界。短高度窗口会压缩导航并隐藏账号文字，避免内容覆盖。

### 7.8 组件体积超限

`DashboardHero.vue` 与 `AppShell.vue` 的大型 scoped CSS 已抽离。最终所有 Vue 组件均小于 300 行。

### 7.9 开发态局部样式退化

修复 Prompt Cards 与 MapStatusBar 在开发态热更新后可能出现 scoped hash 不一致、子节点退化为浏览器默认样式的问题。两个组件改用唯一 BEM 类名和非 scoped 样式，并移除脆弱的直接子元素/标签选择器；生产构建会额外检查关键选择器是否存在。

## 8. 视觉与交互改造

### Agent 工作状态

- Header 明确显示连接/分析状态。
- 空态说明“提出问题后 Agent 会规划任务、调用工具并生成地图图层”。
- 时间线用竖向状态轨道表达执行顺序。
- running 使用旋转状态；success、error 与 pending 使用独立语义色。
- 分析结论与工具过程分层呈现，避免把所有内容压进一个消息气泡。

### Prompt Cards 与输入框

- 示例从短按钮升级为包含分析类型、任务描述和能力上下文的 Prompt Cards。
- 输入框高度、圆角、字号和 focus glow 均增强。
- 保留 Enter 发送、Shift+Enter 换行及四项快捷操作。

### Map Canvas

- `MapStatusBar` 明确展示当前分析、区域、数据源和结果数量。
- 空闲态显示 Map Canvas Ready，执行态显示 Agent 构建图层动画。
- Legend 覆盖 POI、Heatmap、Trajectory、Recommendation。
- Insight 与 Top-1 卡片均可点击并联动地图定位。
- Heatmap 使用冷色低密度到暖色高密度的分析色带。
- Trajectory 增加独立 glow layer 和紫色虚线主轨迹。
- 推荐候选使用紫色 marker、强化描边与 Top-1 halo。

### Candidate Cards

- 每张候选卡展示 Rank、POI 名称、类别、真实 Score 与推荐理由。
- Score 使用相对最高分的可视进度条。
- 命中真实目标时使用成功态强调。
- 点击候选卡保持既有地图 flyTo 联动。

## 9. 工程边界

本次没有修改：

- Backend API
- SSE 事件名称与载荷协议
- Agent 路由与回复逻辑
- Tool 实现
- 数据库与迁移
- `MapContainer` 生命周期
- `useMap` 核心编排方式

工作区中原有的后端未提交变更保持原样，本次任务没有覆盖或回退它们。

## 10. 验证结果

| 检查项 | 结果 |
| --- | --- |
| `npm.cmd run lint` | 通过 |
| `npm.cmd run build` | 通过，2330 modules transformed |
| Vue 组件 `< 300` 行 | 通过 |
| Agent/Map UI 原始 JSON 检查 | 通过，无匹配 |
| 模拟推荐分数检查 | 通过，无匹配 |
| 后端接口/协议修改 | 无 |

构建仍存在既有的 chunk size warning（Mapbox、Element Plus/ECharts 相关包体较大），属于非阻塞性能优化项，不属于本次 UX 升级范围。

## 11. 浏览器验证限制

当前执行环境没有可用的 in-app browser 实例，Python 环境也没有安装 Playwright，因此无法在本轮自动生成页面截图或执行浏览器点击回归。没有为此向项目新增测试依赖。

建议人工验收以下路径：

1. `/agent`：分别触发 POI、热力、推荐和轨迹任务，观察 SSE 时间线状态变化。
2. 推荐任务完成后，点击 Insight 与 Top-1 卡片，确认地图 flyTo。
3. `/recommendation`：切换 session 并点击 Candidate Card，确认候选定位。
4. 以 1440×900、1280×800、移动端窄屏检查布局与滚动边界。

## 12. 结论

Stage 5.5 已把 GeoAgent 的核心体验从“聊天框 + 地图”升级为“Agent 执行空间任务 + 地图呈现结果”。工具状态、参数、结论、图层与推荐解释形成了连续的产品叙事，同时保持现有后端能力和协议零改动。
