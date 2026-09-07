# 第五阶段 P0 报告：产品化打磨（Stage 5 P0 Report）

> 日期：2026-08-01
> 目标：将技术 Demo 打磨为秋招展示级产品（审计结论见 `docs/stage5_product_audit.md`）。
> 范围：仅执行审计中 **P0 优先级**任务；不新增后端能力；Agent 后端链路 / Tool / Service / Repository / PostGIS / 推荐模型逻辑零改动。

---

## 一、修改文件（8）

| 文件 | 变更 |
|---|---|
| `frontend/src/components/common/AppShell.vue` | 品牌区 "Next POI / Geo Intelligence" → "GeoAgent / AI 地理推荐与空间分析平台"，Logo N→G，eyebrow → GeoAgent Platform；导航重排（Agent 置顶）；model-analysis / spatial 入口标记 `hidden: true`（组件与路由保留） |
| `frontend/src/views/dashboard/Dashboard.vue` | 接入 DashboardHero（首屏叙事）；移除 UserBehaviorChart 引用；首页图表仅剩真实接口数据 |
| `frontend/src/views/dashboard/DashboardHeader.vue` | h2 → "GeoAgent 推荐与时空分析概览"；描述并入产品定位文案 |
| `frontend/src/views/dashboard/DashboardHero.vue`（新增） | 首屏 Landing 组件（详见第三节） |
| `frontend/src/components/agent/AgentChat.vue` | 空态区：能力清单 + ExamplePrompts 引导；聊天核心逻辑（流式 / 回退 / session_id）零改动 |
| `frontend/src/views/RecommendationView.vue` | 结果卡片组件化瘦身（274 行），页面只保留数据加载 / 地图 / 分页布局 |
| `frontend/index.html` | title → "GeoAgent - 基于真实签到数据的 AI 地理推荐与空间分析平台" |
| `README.md` | 标题与简介统一 GeoAgent 品牌与产品定位；docs 索引新增 stage5 文档 |

## 二、新增文件（4）与删除文件（1）

**新增：**

| 文件 | 职责 | 行数 |
|---|---|---|
| `frontend/src/views/dashboard/DashboardHero.vue` | 首页 Hero：产品名 + 一句话介绍 + 3 能力卡片 + 主 CTA | 146 |
| `frontend/src/components/agent/ExamplePrompts.vue` | Agent 空态 4 个示例问题 chips（点击 emit select） | 74 |
| `frontend/src/composables/useRecommendationExplanation.ts` | 从真实信号派生推荐理由（rank / score / 类别与历史交集；无信号 → null） | 56 |
| `frontend/src/components/recommendation/RecommendationResultCard.vue` | Top-K 表格 + Top-1 解释卡 + 真实目标（单卡职责） | 130 |

**删除：** `frontend/src/views/dashboard/UserBehaviorChart.vue`（硬编码时段活跃度假数据，注释自述"占位，后续接入真实接口"）。

## 三、页面变化

### 首页 `/dashboard`
- 首屏新增 Hero：GeoAgent 品牌 + 一句话介绍（LLM Agent / PostGIS / 下一 POI 推荐模型）+ 3 能力卡片（AI Agent → /agent、GIS Spatial Intelligence → /poi-map、Recommendation → /recommendation）+ 主 CTA「体验 GeoAgent」→ /agent
- **删除假数据卡**（用户行为节律图）；保留全部真实接口图表（指标卡 / 模型对比图）

### Agent 页 `/agent`
- 空态从一句提示升级为：能力说明（✓ POI 查询 / 空间热力分析 / 下一地点推荐 / 用户轨迹分析）+ 4 个示例问题 chips（点击即发送）
- 聊天链路（流式 / 回退 / 多轮记忆）未改动

### 推荐页 `/recommendation`
- 新增 **Top-1 推荐解释卡**：推荐地点 / 推荐分数 / 推荐原因列表
- 候选表格新增「推荐理由」列（超长 tooltip 截断）
- 理由由 `useRecommendationExplanation` 从详情接口真实信号派生（语义与后端 Stage 4 `_explain_candidates` 一致，**不编造**）：排名第一 → "模型评分最高（真实分数）"；类别与历史访问重合 → "与您历史访问过的类别「X」相关"；无以上信号 → "基于您的历史签到序列的个性化预测"；候选缺失基础信号 → 显示「暂无解释信息」

### 导航
- 顺序调整为：**Agent 对话 → 数据看板 → POI 地图 → 用户轨迹 → 推荐结果**（Agent 置顶）
- 空间分析 / 模型分析：`hidden: true` 仅移除导航入口，**组件与路由代码保留**

### 品牌
- AppShell 品牌区、DashboardHeader、浏览器 title、README 全部统一 **GeoAgent**
- 产品定位统一：**"基于真实签到数据的 AI 地理推荐与空间分析平台"**

## 四、验证结果

```
cd frontend && npm run lint   → 0 errors, 0 warnings ✅
cd frontend && npm run build  → vue-tsc 通过 + ✓ built in 16.84s ✅
```

- **console 错误**：全部改动代码无 console 调用（新增代码零 console）
- **undefined 字段**：vue-tsc 严格类型检查通过；`reason` 可能为空的路径由「暂无解释信息」兜底（`NO_EXPLANATION` 常量）；`score.toFixed` 仅在 `typeof score === "number"` 的派生路径下渲染（deriveReason 对非 number 信号返回 null）
- **行数约束**：全部前端文件 <300 行（最大 RecommendationView.vue 274 行）；函数 <100 行
- **后端**：零改动（未触碰 Agent 链路 / Tool / Service / Repository / PostGIS / 模型逻辑），无需回归 pytest

## 五、说明与遗留

1. **reason 数据源**：推荐详情接口（`GET /api/recommendations/{uid}/{sid}`）本身不返回解释字段（Stage 4 的 reason 生成在 Agent 链路 RecommendTool）。经确认，P0 采用**前端从真实信号派生**方案（不修改后端），派生语义与后端一致；后续若后端详情接口补返回 reason，前端组件可直接透传（`explainCandidates` 的产物结构已预留 `reason` 字段，接口返回时会自然覆盖）。
2. **P1 / P2 未执行**（按任务范围）：首页数据集规模、地图图例 / 点位弹窗、消息自动滚动、清空会话、实验页路由移除等留待后续批次。
3. 后端接口与页面全部保留（`/spatial`、`/model-analysis` 路由仍可直达），仅隐藏导航入口，符合"不删除代码"要求。
