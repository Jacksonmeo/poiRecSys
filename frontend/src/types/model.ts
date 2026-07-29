/**
 * 模型评估指标。
 * input: 后端 /metrics/models 与相关实验接口返回的单模型记录。
 * output: Dashboard、Model Analysis 等页面用于展示和排序的强类型数据。
 */
export interface ModelMetric {
  model: string
  hr5: number
  ndcg5: number
  mrr10: number
}

export interface DashboardMetricItem {
  label: string
  value: number | string
  suffix?: string
  trend?: string
  tone: "primary" | "success" | "warning" | "violet"
}
