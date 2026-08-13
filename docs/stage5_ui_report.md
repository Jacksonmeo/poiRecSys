# Stage 5.5 报告：AI Spatial Intelligence Workspace UI 重构（Stage 5.5 Report）

> 日期：2026-08-01
> 目标：将页面从「后台式工具」升级为 AI Spatial Intelligence Workspace。
> 设计稿：`docs/stage5_ui_redesign.md`（评审通过后实施）。
> 核心约束（全部遵守）：Agent 后端接口与 SSE 事件协议零改动；仅前端渲染层升级；不引入新 UI 框架。

---

## 一、实施结果（7 步，每步 lint + build 全绿）

| 步骤 | 内容 | 关键文件 | 验证 |
|---|---|---|---|
| **Step 1** | 色板与 Design Token | `styles/variables.css`、`styles/main.css` | lint 0 + build ✅ |
| **Step 2** | Workspace 布局 | `AgentView.vue`、`usePanelResize.ts`、`AgentPanelHeader.vue`、`AgentChat.vue` | lint 0 + build ✅ |
| **Step 3** | PromptInput | `PromptInput.vue`（新增）、`ChatInput.vue`（删除） | lint 0 + build ✅ |
| **Step 4** | Tool 状态机 | `useToolExecution.ts`、`ToolExecutionState.vue`、`MessageList.vue`、`types/agent.ts`、`ToolCallCard.vue`（删除） | lint 0 + build ✅ |
| **Step 5** | Mapbox 视觉升级 | `useMap.ts`、`poiLayer.ts`、`trajectoryLayer.ts`（新增）、`heatmapLayer.ts`、`MapLegend.vue`、`MapStatusBar.vue`、`MapLayerRenderer.vue` | lint 0 + build ✅ |
| **Step 6** | 推荐卡片 | `RecommendationCard.vue`、`RecommendationResultCard.vue`、`RecommendationView.vue` | lint 0 + build ✅ |
| **Step 7** | 全量验证 | 见第四节 | 全绿 |

## 二、组件清单

### 新增（9）

| 文件 | 职责 | 行数 |
|---|---|---|
| `composables/usePanelResize.ts` | 聊天面板拖拽调宽（默认 420 / min 360 / max 520） | 39 |
| `composables/useToolExecution.ts` | Tool 状态机（tool_call→running / tool_result→success）+ TOOL_META 语义表 | 51 |
| `components/agent/AgentPanelHeader.vue` | Agent 身份 + 会话状态点（在线/思考中）+ 清空会话 | 76 |
| `components/agent/PromptInput.vue` | Prompt Card：多行输入 + 焦点光晕 + 快捷示例 + 发送 | 134 |
| `components/agent/ToolExecutionState.vue` | 工具状态卡：名称/参数 chips/状态徽标/结果摘要/原始参数展开 | 171 |
| `components/map/MapLegend.vue` | 右下图层图例（按 layers 动态显示轨迹/POI/热力） | 79 |
| `components/map/MapStatusBar.vue` | 左上结果状态条（模式推断 + 结果计数） | 64 |
| `components/recommendation/RecommendationCard.vue` | 单条候选卡（rank 徽章/分数条/理由/命中高亮） | 161 |
| `map/layers/trajectoryLayer.ts` | 轨迹图层模块（glow 线/空心点/起点绿/终点红/编号标签） | 85 |

### 修改（10）

| 文件 | 变更 |
|---|---|
| `AgentView.vue` | 面板化布局（无卡片包裹/无间隙）+ 拖拽分隔条 + 响应式堆叠 |
| `AgentChat.vue` | 接入 PanelHeader / PromptInput / 工具状态机（复用既有 onToolResult handler） |
| `MessageList.vue` | 工具卡渲染由 toolCalls → executions（ToolExecutionState） |
| `types/agent.ts` | 新增 ToolStatus / ToolExecution 类型 + AgentChatMessage.executions |
| `useMap.ts` | 底图 light-v11、zoom 10.6、图层注册委托模块、hover 放大（feature-state）、popup 卡片化、轨迹首尾语义 |
| `poiLayer.ts` | 完整图层模块：rank=1 光晕、半径分级、hover 放大、排名标签 |
| `heatmapLayer.ts` | 色带对齐新色板（浅青→cyan→深靛） |
| `MapLayerRenderer.vue` | 挂载地图悬浮层（左上状态条 + 右下图例） |
| `RecommendationResultCard.vue` | 表格 → 候选卡列表 + 命中真实目标高亮 + select 事件上抛 |
| `RecommendationView.vue` | 候选卡点击 → flyToPoint 地图联动 |
| `styles/variables.css` | 色板重构 + 状态语义 token + EP 主色对齐 |
| `styles/main.css` | 背景渐变弱化 + map-popup 全局样式 |

### 删除（2）

`ChatInput.vue`（被 PromptInput 取代）、`ToolCallCard.vue`（被 ToolExecutionState 取代）。

## 三、页面变化

### Agent 工作台 `/agent`
- **布局**：两栏面板化（拖拽分隔条调整聊天宽度 360-520px，默认 420px）；Agent Panel Header（身份 + 在线/思考中状态 + 清空会话——通过重新生成 session_id 等效清空记忆，**不新增后端接口**）
- **输入区**：Prompt Card（多行自适应、Enter 发送/Shift+Enter 换行、焦点光晕、底部 4 个快捷示例、发送中 loading）
- **工具执行**：SSE 事件序列驱动的状态机——tool_call 到达显示"执行中"（spinner），tool_result 到达转"✓ 完成"并显示结果摘要（如"共 12 条结果"），失败显示"⚠ 失败"；参数摘要 chips + 原始 JSON 可展开（面试讲解保留）
- **地图画布**：light-v11 浅色底图；POI rank=1 光晕焦点 + 半径分级 + hover 放大；轨迹 glow 线 + 起点绿点/终点红点；密度热力新色带；点位 popup 卡片化（名称/类别/排名/坐标）；左上结果状态条 + 右下图层图例

### 推荐页 `/recommendation`
- 候选表格 → **候选卡列表**：rank 徽章 + 展示名 + 分数条（相对最高分）+ 类别 + 理由一行截断
- **命中真实目标**高亮（venue_id 比对，纯真实字段）：绿色边框 + "命中真实目标"徽章
- 点击候选卡 → 地图飞至该 POI（联动）

### 全站
- 色板统一：深靛品牌主色 #2563eb + cyan 空间语义色 + 状态 token（running/success/error）；Element Plus 主色对齐

## 四、验证结果

```
cd frontend && npm run lint   → 0 errors, 0 warnings ✅
cd frontend && npm run build  → vue-tsc 通过 + ✓ built in 17.29s ✅
cd backend && python -m pytest → 78 passed（前端零回归）✅
```

- **行数约束**：全部文件 <300 行（最大 RecommendationView.vue 283、useMap.ts 272）；函数 <100 行
- **console**：除既有 useMap token 缺失提示外，新增代码零 console 调用
- **undefined 防御**：ToolStatus 全分支渲染；reason 空值由「暂无解释信息」兜底；地图悬浮层在无图层时整体隐藏

## 五、约束遵守确认

| 约束 | 状态 |
|---|---|
| Workspace 默认 420px / min 360px / max 520px | ✅ usePanelResize 常量 |
| Tool 状态机复用现有 SSE 事件，后端接口/事件协议零改动 | ✅ onToolResult 为既有 handler 接线；后端 pytest 78/78 |
| 推荐展示优先 rank / score / reason / 真实目标命中 | ✅ 候选卡四要素 + 命中高亮 |
| Mapbox 只调 style 与图层展示，MapContainer 生命周期契约不变 | ✅ MapContainer.vue 零改动，expose 方法未变 |
| 输入逻辑保留在 PromptInput 组件内 | ✅ AgentChat 仅监听 send 事件 |
| 不引入新 UI 框架 | ✅ 全部自研组件 + 既有 Element Plus/Mapbox |
| 每步 lint/build | ✅ 7 步全部通过 |

## 六、遗留（未做，属于 P1/P2 或后续阶段）

1. 清空会话为前端等效实现（新 session_id），后端 `memory.clear` 仍未暴露 HTTP 端点（如需真实清库再议）。
2. 消息自动滚动（near-bottom 阈值）未实施——本阶段消息量小影响低。
3. 推荐页地图初始视角与 POI 地图图例复用（MapLegend 已组件化，接入其他页留待后续）。
