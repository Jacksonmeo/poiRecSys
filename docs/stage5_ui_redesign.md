# Stage 5.5 设计稿：AI Spatial Intelligence Workspace（UI 重构）

> 日期：2026-08-01
> 目标：在 Stage 5 P0（品牌/假数据/Hero/引导/推荐解释）基础上，将页面从「后台式工具」升级为
> **AI Spatial Intelligence Workspace**——以 Agent 为主舞台、地图为结果画布的工作台。
> 本文件为设计稿，**不含代码修改**，评审通过后按「十、实施顺序」执行。
> 约束：保持 Vue 3 + TypeScript；**Agent 后端接口与 SSE 事件协议不变**；不新增后端能力。

---

## 一、现状评估（设计基准）

| 模块 | 现状 | 问题 |
|---|---|---|
| **Agent Workspace** | `AgentView.vue`：固定 380px 聊天卡 + 弹性地图卡（两栏 el-card） | 宽度不可调；两栏视觉割裂（两个独立卡片中间有间隙）；无会话工具条 |
| **Chat 区域** | `AgentChat`：空态引导 + 消息气泡 + ChatInput（单行 el-input） | 气泡无元信息；工具卡片与文本并列无时序感；输入框单行、无焦点态、无快捷发送体验 |
| **Tool 展示** | `ToolCallCard.vue`：工具名 + 可展开的原始 JSON 参数 | **无执行状态**（无 running/success/error）；无结果摘要；原始 JSON 对非技术观众不可读 |
| **Mapbox** | `useMap.ts`：streets-v12 亮色底图 + POI 圆点（分类色）+ 轨迹线（纯色）+ heatmap + 简单 popup | 底图噪点多；POI 无 hover 反馈/无分级；轨迹无方向语义；无图例、无结果区域指示；popup 无排名信息 |
| **推荐结果** | `RecommendationResultCard.vue`（P0 交付）：Top-1 解释卡 + 表格 + 理由列 | 表格仍是"评测表"形态；无命中真实目标高亮；与地图无交互联动 |
| **颜色体系** | `variables.css`：浅色 SaaS 蓝（#246bfe）+ 玻璃拟态 | 与"AI Workspace"气质有差距；语义 token 不足（状态色/空间色混用） |

**可用而未用的现成能力**：`sendAgentMessageStream` handlers 已含 `onToolResult`（AgentChat 未使用）——Tool 状态机**无需改接口**即可实现。

## 二、设计原则（从参考产品提炼，不复制）

| 原则 | 来源启发 | 落地 |
|---|---|---|
| **对话是流水线，不是纸条** | Linear / Vercel AI 产品：工具调用是对话的一部分，时序可见 | 工具卡片按执行顺序嵌入消息流，带状态徽标与结果摘要 |
| **输入框是舞台中央** | Perplexity / Vercel：输入区是主 CTA，空态即演示 | Prompt Card 大输入区 + 空态示例卡常驻 |
| **地图是结果画布** | Carto：空间产品里地图承担叙事，解释层（图例/状态）叠在画布上而非旁边 | 图例/结果摘要/区域指示以悬浮层叠在地图四角 |
| **克制的中性 + 语义色** | Linear：大量中性灰 + 单一品牌色 + 语义状态色 | 色板重构：中性冷灰底 + 品牌深靛 + cyan 空间语义色；分类色仅用于地图 |
| **状态必须可见** | SaaS 工作台惯例：异步流程每一步可感知 | Tool 卡片状态机：pending → running → success/error |
| **一切改动不触碰契约** | 项目治理约束 | Agent 接口/事件协议/SDK 零改动，纯前端渲染层升级 |

## 三、重点设计 1：Agent Workspace 布局调整

### 3.1 目标布局（两栏工作台）

```
┌──────────────────────────────────────────────────────────────────────┐
│ AppShell header（GeoAgent 品牌 + 当前页描述）                           │
├───────────────────────────────┬──────────────────────────────────────┤
│ Agent Panel（可拖拽宽度 320-560px）│ Map Canvas（结果画布）                │
│ ┌───────────────────────────┐ │ ┌──────────────────────────────────┐ │
│ │ Panel Header              │ │ │ 左上：MapStatusBar（当前区域/模式）│ │
│ │ Agent 标识 + 会话状态 + 清空│ │ │ 右上：导航控件 + 图层控制           │ │
│ ├───────────────────────────┤ │ │                                  │ │
│ │ 消息流（空态：能力+示例卡）   │ │ │        Mapbox GL                │ │
│ │   - 用户气泡（右）           │ │ │    （light 底图 + 升级图层）       │ │
│ │   - Tool 流水线卡片          │ │ │                                  │ │
│ │   - AI 文本（打字机）         │ │ ├──────────────────────────────────┤ │
│ ├───────────────────────────┤ │ │ 右下：MapLegend（图层图例）        │ │
│ │ Prompt Card（输入区）        │ │ └──────────────────────────────────┘ │
│ └───────────────────────────┘ │                                      │
└───────────────────────────────┴──────────────────────────────────────┘
```

### 3.2 布局要点

1. **Agent Panel 可调宽**：拖拽分隔条（240px ≤ width ≤ 560px），默认 420px。抽离 `usePanelResize` composable（拖拽事件 + 宽度 clamp，纯前端）。
2. **面板化而非卡片化**：去掉两栏的 el-card 边框包裹，改为同一画布上的两个分区（无间隙、无双重边框），与 AppShell 一体。
3. **Agent Panel Header**（新增 `AgentPanelHeader.vue`）：Agent 身份（图标 + "GeoAgent Assistant"）、会话状态点（idle/working，由 sending 状态驱动）、清空会话按钮（调后端 `memory.clear`，P2 遗留项顺带入）。
4. **Map Canvas**：地图占满剩余空间，地图上方悬浮层（图例/状态条）见第六节。
5. **响应式**：<1200px 时聊天面板收窄至 360px；<991px 堆叠（上地图 55vh 下对话），沿用现有断点惯例。
6. `AgentChat` 保留为主组件（布局与消息状态），新增的 Panel Header / 状态通过插槽或 props 接入——**不重写聊天编排逻辑**。

## 四、重点设计 2：Chat 区域重新设计

| 现状 | 升级 |
|---|---|
| 用户/AI 气泡 + 工具卡并列 | 消息流按"时序叙事"组织：用户问题 → 工具流水线 → AI 结论 |
| 气泡无元信息 | AI 气泡附带轻量元信息行（工具调用次数摘要），不堆时间戳 |
| 无自动滚动 | `useChatAutoscroll`：新消息到达滚动到底；用户上滚查看历史时不强制下拉（near-bottom 阈值判断） |
| 工具卡在气泡下方平铺 | 工具卡内联进 AI 消息流，成为"执行段落"（见第五节） |

- **用户气泡**：右对齐品牌主色底（保持现样式，圆角微调 12px，max-width 88%）。
- **AI 段落结构**：`AI 文本（打字机）` + 其下 `工具流水线卡片`。顺序由事件流决定（tool_call 先于 text 到达，天然形成"先执行后结论"）。
- **空态**：保留 P0 交付的能力清单 + 示例卡，升级为居中组合（标题 + 4 能力 + 4 示例卡网格），视觉对齐 Prompt Card。
- **MessageList** 仅改模板结构（段落容器），消息数据结构（`AgentChatMessage`）不变——聊天核心逻辑不动。

## 五、重点设计 3：Prompt Card 设计

**新组件 `PromptInput.vue`**（替代现有 ChatInput）：

```
┌────────────────────────────────────────────────┐
│  帮我找涩谷附近的咖啡店                            │
│  试试：找咖啡店 / 空间密度 / 给我推荐 / 查看轨迹    │
├────────────────────────────────────────────────┤
│  ⚡ 快捷示例（4 chips，点击即发送）      [发送 ➤]  │
└────────────────────────────────────────────────┘
```

1. **多行自适应**：`el-input type="textarea" :autosize="{ minRows: 1, maxRows: 4 }"`，Enter 发送 / Shift+Enter 换行（当前为单行 el-input）。
2. **焦点态**：聚焦时主色边框 + 阴影光晕（focus-ring），形成"舞台中央"观感。
3. **快捷示例行**：输入框底部常驻 4 个 prompt chips（复用 P0 的 `ExamplePrompts` 文案，但作为**点击即发送**的快捷行，与空态示例卡语义区分——空态是"演示入口"，这里是"快捷补充"）；`disabled`（发送中）时整体置灰。
4. **发送按钮**：右侧圆形主色按钮，文本为空时禁用；发送中转为 loading 态。
5. 语义保持：`emit("send", message)` 不变，AgentChat 的 send 编排零改动。

## 六、重点设计 4：Tool 执行状态展示

### 6.1 状态机（零接口改动）

SSE 事件序列已隐含状态：`tool_call → tool_result → (text|done)`。前端在 AgentChat 中新增 `useToolExecution` composable 管理状态：

```
tool_call 到达 → 卡片创建，状态 running（spinner + "执行中"）
tool_result 到达 → 状态 success（✓ + 业务摘要，如 "共 12 个 POI"）
流式失败 / error 事件 / 回退非流式 → 状态 error（⚠ + "执行失败"）
```

- `onToolResult` 回调**已存在于 `sendAgentMessageStream` handlers**（当前未使用），直接接线；非流式路径（`sendAgentMessage` 响应 `tool_calls`）统一标记 success。
- 工具语义元数据（前端静态表）：`query_poi → 查询 / spatial_density → 热力分析 / recommend → 推荐 / track → 轨迹`，配图标（复用 @element-plus/icons-vue 现有图标，不新增依赖）。

### 6.2 卡片形态（升级 ToolCallCard）

```
┌─────────────────────────────────────────────┐
│ [🔍] query_poi                ✓ 完成        │   ← 图标 + 工具名 + 状态徽标
│   category: Coffee Shop · location: 涩谷    │   ← 参数摘要 chips（非原始 JSON）
│   共找到 12 个 POI                           │   ← 结果摘要（tool_result_summary）
│   ──────────────────────────────            │
│   查看参数 [▸]（展开原始 JSON，技术面试保留）    │
└─────────────────────────────────────────────┘
```

1. **参数摘要**：按工具参数 schema 生成人类可读 chips（location/category/top_k/user_id），原始 JSON 折叠保留（面试讲实现时展开）。
2. **状态徽标**：running = 旋转 loading 图标 + "执行中"；success = 绿色 ✓ + 结果摘要；error = 红色 ⚠。
3. **时序编号**：同一轮多次工具调用按事件顺序显示 #1 #2（后端单轮多工具能力是 P2，前端结构先行兼容）。

## 七、重点设计 5：Mapbox 视觉升级

### 7.1 底图

- `streets-v12` → `mapbox://styles/mapbox/light-v11`（克制的浅色底图，街道文字淡、无高饱和 POI 噪声），符合"地图是画布"。
- 默认视角升级：`zoom 10 → 10.6`，`center` 保持东京中心；新增 `minPitch 0`（维持俯视，不开启 3D 俯仰，避免喧宾夺主）。

### 7.2 图层视觉（useMap paint 调整 + poiLayer/heatmapLayer 样式）

| 图层 | 升级 |
|---|---|
| **POI 圆点** | 半径分级：`rank === 1` → 10px + 主色光晕（circle-blur 渐变层）；`rank ≤ 3` → 8px；其他 6px；hover 高亮（mouseenter 时 radius ×1.4 + 白描边加粗） |
| **POI 标签** | rank 徽章文字加白 halo（已有），字号 12 → 13；仅 rank>0 显示（已有 filter） |
| **轨迹线** | 主色 cyan 线 + `line-blur: 3`（glow 感）；起点/终点语义：起点 = 绿色圆点、终点 = 红色圆点（用 sequenceNo 首尾识别，数据已有字段） |
| **轨迹点** | 保持编号标签；圆点改为空心（白色填充 + 彩色描边），与 POI 实心点区分 |
| **热力图** | color ramp 对齐新色板（低密度透明 → 高密度 cyan→深靛），沿用 `heatmapLayer.ts` 的 source 结构（改 paint 常量即可） |
| **Popup** | 卡片式 HTML：标题 + 类别 chip + 排名（若有）+ 坐标 + venue_id（小字）；`closeButton: false` 保留，加 `offset` |

### 7.3 地图悬浮层（新增组件，叠在 MapLayerRenderer 上层）

1. **`MapLegend.vue`**（右下）：当前图层的图例（轨迹线/POI 分类色/真实目标/热力），按 `layers` prop 动态显示对应条目；地图页（PoiMap/轨迹页）也可复用。
2. **`MapStatusBar.vue`**（左上）：轻量状态条——当前 Agent 模式（"POI 查询 / 热力分析 / 推荐 / 轨迹 / 空闲"）+ 结果计数摘要；无工具执行时不显示（不占空间）。

> 悬浮层放 `MapLayerRenderer` 内部（position: absolute 叠在 MapContainer 上），复用现有 layers prop 驱动，不改 MapContainer/useMap 生命周期。

## 八、重点设计 6：推荐结果展示方式

`RecommendationResultCard` 从「评测表」升级为「解释清单」：

```
┌──────────────────────────────────────────────┐
│ Top-1 推荐解释（保留 P0 交付，样式对齐色板）      │
├──────────────────────────────────────────────┤
│ ┌──────────────────────────────────────────┐ │
│ │ [1] ☕ Central Coffee        0.95 ███████ │ │  ← rank 徽章 + 名称 + 分数条
│ │     Coffee Shop · 理由：模型评分最高…      │ │  ← 类别 chip + 理由（tooltip 截断）
│ └──────────────────────────────────────────┘ │
│ ┌──────────────────────────────────────────┐ │
│ │ [2] ...  （同结构）                        │ │
│ └──────────────────────────────────────────┘ │
│ 真实目标：XXX ✓ 命中 Top-3                    │ ← 命中真实目标高亮（P1 R4 纳入）
└──────────────────────────────────────────────┘
```

1. **候选卡片化**：表格 → 纵向候选卡列表（排名徽章 + 展示名 + 类别 chip + 分数条 + 理由一行截断），`RecommendationCard.vue` 单卡组件；分数条宽度 = score 相对 max 比例（视觉对比，不新增数据）。
2. **命中高亮**：候选 venue_id 与 target_poi.venue_id 相等 → 卡边框 success 色 + "命中" 徽章（数据完全真实，来自既有字段）。
3. **地图联动**：点击候选卡 → `flyToPoint`（RecommendationView 已有 mapRef 引用，事件上抛即可）。
4. Top-1 解释卡保留（P0 交付物），与候选卡同组件族；`useRecommendationExplanation` 复用。

## 九、重点设计 7：页面颜色体系

### 9.1 色板重构（variables.css 扩展，向后兼容——旧变量名保留映射）

| Token | 现值 | 新值 | 语义 |
|---|---|---|---|
| `--color-bg` | `#f4f7fb` | `#f6f8fb` | 更冷的浅灰蓝底 |
| `--color-primary` | `#246bfe` | `#2563eb` | 品牌主色：深靛蓝（AI 主舞台） |
| `--color-cyan` | `#06aed4` | `#0891b2` | **空间语义色**（地图/轨迹/Agent 活跃） |
| `--color-violet` | `#7a5af8` | `#7c3aed` | 推荐语义色（推荐工具/徽章） |
| `--color-success/warning/danger` | 现值 | 微调同族 | 状态语义（✓ 命中 / ⚠ 风险 / ✗ 失败） |

**新增语义 token**：
- `--color-agent: #2563eb`（Agent 身份）
- `--color-map-hover: rgba(37, 99, 235, 0.14)`（地图 hover 反馈）
- `--color-status-running: #0891b2`、`--color-status-success: #16a34a`、`--color-status-error: #dc2626`（Tool 状态机专用，与图表语义色解耦）
- `--shadow-input-focus`（Prompt Card 焦点光晕）
- `--font-mono` 显式声明（ToolCallCard 参数展开已引用，当前为未定义 fallback）

### 9.2 应用规则

1. **分类色板只属于地图**（Transport/Shopping/Culture/Park/Landmark/真实目标保留，`colorForCategory` 不变量）。
2. Element Plus 主题：仅覆盖 `--el-color-primary` 主色（main.ts 或全局变量注入），组件库其余保持默认，减少定制面。
3. 玻璃拟态（glass-panel）保留但统一为低透明度中性白，不再叠加彩色渐变背景（body 背景渐变弱化，向 Linear 式纯色底靠拢——一步到位有回归风险，**先弱化渐变不删除**）。

## 十、重点设计 8：Vue 组件拆分方案

### 10.1 新增（7）

| 组件 | 目录 | 职责 | 预估行数 |
|---|---|---|---|
| `AgentPanelHeader.vue` | components/agent/ | Agent 身份 + 会话状态点 + 清空会话 | ~90 |
| `PromptInput.vue` | components/agent/ | 多行输入 + 焦点态 + 快捷 chips + 发送按钮 | ~120 |
| `MapLegend.vue` | components/map/ | 图层图例（按 layers 动态显示） | ~100 |
| `MapStatusBar.vue` | components/map/ | 左上结果状态条（模式 + 计数） | ~90 |
| `RecommendationCard.vue` | components/recommendation/ | 单条候选卡（徽章/分数条/理由/命中） | ~110 |
| `ToolExecutionState.vue` | components/agent/ | Tool 卡片状态机渲染（含摘要 chips） | ~140 |
| `SpatialStatus`（如需要） | components/map/ | 当前区域指示（设计 7.3 可选合并进 StatusBar） | — |

### 10.2 修改（8）

| 组件/模块 | 变更 |
|---|---|
| `AgentView.vue` | 面板化布局 + 拖拽分隔条 + 地图悬浮层挂载 |
| `AgentChat.vue` | 接入 Panel Header / PromptInput / 状态机接线（onToolResult） |
| `ChatInput.vue` | **删除**（被 PromptInput 取代） |
| `ToolCallCard.vue` | **重写**为 ToolExecutionState（或整体替换） |
| `useMap.ts` | paint 视觉升级（底图/分级/hover/轨迹首尾/光晕）+ popup 升级 |
| `heatmapLayer.ts` / `poiLayer.ts` | color ramp / 常量对齐新色板 |
| `RecommendationResultCard.vue` | 表格 → 候选卡列表 + 命中高亮 + 点击联动事件 |
| `variables.css` / `main.css` | 色板 token 扩展 + 焦点光晕 + 背景弱化 |

### 10.3 新增 composables（3）

| composable | 职责 |
|---|---|
| `usePanelResize.ts` | 拖拽分隔条（宽度 clamp + 事件生命周期） |
| `useToolExecution.ts` | Tool 状态机（pending/running/success/error + 摘要映射） |
| `useChatAutoscroll.ts` | 消息流自动滚动（near-bottom 判定） |

### 10.4 明确不动

后端全部（Agent 接口 / SSE 协议 / Tool / Service / Repository）；`MapContainer.vue`（生命周期与 expose 契约）；`MapLayerRenderer.vue`（分派逻辑）；`types/agent.ts`（消息/图层类型）；`AgentChatMessage` 数据结构。

## 十一、改造前后布局图

### 改造前（现状）

```
┌────────────────────────────────────────────────────┐
│ AppShell: [菜单]  GeoAgent | header 描述            │
├───────────────┬────────────────────────────────────┤
│ ┌───────────┐ │ ┌────────────────────────────────┐ │
│ │ el-card   │ │ │ el-card                        │ │
│ │ 空态/消息流│ │ │  Mapbox streets-v12            │ │
│ │ 单行输入   │ │ │  （无图例/无状态条）            │ │
│ └───────────┘ │ └────────────────────────────────┘ │
│ 380px 固定     │                                    │
└───────────────┴────────────────────────────────────┘
```

### 改造后（目标）

```
┌────────────────────────────────────────────────────┐
│ AppShell: [菜单]  GeoAgent | 描述                  │
├──────────────┬─────────┬───────────────────────────┤
│ Agent Panel  │ 拖拽条  │ Map Canvas                 │
│ ┌──────────┐ │         │ ┌───────────────────────┐ │
│ │ PanelHdr │ │         │ │ MapStatusBar(左上)     │ │
│ ├──────────┤ │         │ │  Mapbox light-v11      │ │
│ │ 消息流    │ │         │ │  升级图层（分级/hover/  │ │
│ │ Tool流水线│ │         │ │  轨迹首尾/光晕）        │ │
│ │ 打字机    │ │         │ │              Nav(右上) │ │
│ ├──────────┤ │         │ │  MapLegend(右下)       │ │
│ │ PromptCard│ │         │ └───────────────────────┘ │
│ └──────────┘ │         │                           │
└──────────────┴─────────┴───────────────────────────┘
```

## 十二、组件修改列表（汇总）

见 10.1-10.3。文件清单：**新增 7 组件 + 3 composable，修改 8 文件，删除 1 文件**（ChatInput.vue）。全部文件保持 <300 行、函数 <100 行、单一职责。

## 十三、实施顺序

| 步骤 | 内容 | 验证 |
|---|---|---|
| **Step 1** | 色板 token 扩展（variables.css/main.css） | lint + build |
| **Step 2** | Workspace 骨架：AgentView 面板化 + `usePanelResize` + AgentPanelHeader | lint + build |
| **Step 3** | PromptInput（替换 ChatInput）+ AgentChat 接入 | lint + build |
| **Step 4** | Tool 状态机：`useToolExecution` + ToolExecutionState（接 onToolResult） | lint + build |
| **Step 5** | Mapbox 视觉：底图/图层 paint/首尾点/popup + MapLegend + MapStatusBar | lint + build |
| **Step 6** | 推荐卡列表：RecommendationCard + ResultCard 改造 + 命中高亮 + 点击联动 | lint + build |
| **Step 7** | 全量验证（lint + build + 逐页走查 console/undefined）+ `docs/stage5_ui_report.md` + changelog + README | 全绿 |

预计约 3-4 天。每步独立可回滚；Agent 接口零改动，后端无需回归（可选跑一遍 pytest 确认前端未误触）。

## 十四、边界声明

1. 不做深色模式、不做 3D 地图、不引入 UI 框架之外的依赖（图例/状态条全部自研组件）。
2. Agent 后端链路、SSE 事件协议、工具行为**保持不变**；`onToolResult` 是既有 handler，接线不视为接口变更。
3. 推荐解释仍由 `useRecommendationExplanation` 派生（Stage 5 P0 决策），本阶段仅改呈现形态。
4. 地图 hover/分级/首尾点全部基于**已有数据字段**（rank/sequence_no/venue_category），不新增接口字段。
