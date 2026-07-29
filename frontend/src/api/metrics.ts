import request from "./request"
import type { ModelMetric } from "@/types/model"

/**
 * 模型评估指标 API。
 * input: 无查询参数。
 * output: 后端返回的模型指标数组，用于 Dashboard 和模型分析页面。
 * API 层统一声明响应类型，避免页面侧出现 any 或重复类型断言。
 */
export const fetchModelMetrics = () => request.get<never, ModelMetric[]>("/metrics/models")

export const fetchAblationMetrics = () => request.get<never, ModelMetric[]>("/metrics/ablation")

export const fetchSeenUnseenMetrics = () =>
  request.get<never, Array<{ group: string; hr5: number; ndcg5: number }>>("/metrics/seen-unseen")
