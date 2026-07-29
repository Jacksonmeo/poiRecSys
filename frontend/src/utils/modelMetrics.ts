import type { DashboardMetricItem, ModelMetric } from "@/types/model"

/**
 * 从模型列表中选择 Dashboard 主展示模型。
 * input: metrics 为后端返回的模型评估数组。
 * output: 优先返回项目方法 Ours；不存在时回退到第一条数据。
 * 这样设计是为了让首页始终突出当前研究方法，同时兼容后端样例数据。
 */
export const resolveBestModel = (metrics: ModelMetric[]) =>
  metrics.find((item) => item.model === "Ours") ?? metrics[0]

export const formatScore = (value?: number) => (typeof value === "number" ? value.toFixed(2) : "-")

/**
 * 生成首页 KPI 卡片数据。
 * input: bestModel 为已选中的模型指标。
 * output: 可直接传给 MetricCard 渲染的结构化数组。
 */
export const buildDashboardMetrics = (bestModel?: ModelMetric): DashboardMetricItem[] => [
  {
    label: "最佳模型",
    value: bestModel?.model ?? "-",
    trend: "当前实验主方法",
    tone: "primary",
  },
  {
    label: "HR@5",
    value: formatScore(bestModel?.hr5),
    suffix: "%",
    trend: "命中率",
    tone: "success",
  },
  {
    label: "NDCG@5",
    value: formatScore(bestModel?.ndcg5),
    suffix: "%",
    trend: "排序质量",
    tone: "violet",
  },
]
