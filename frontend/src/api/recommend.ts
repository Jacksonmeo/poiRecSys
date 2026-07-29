/**
 * 推荐结果 API 接口封装。
 * 对应后端 /api/recommendations 路由组。
 *
 * 列表接口使用服务端分页，避免全量加载数万条 session 导致前端卡顿。
 */
import request from "./request"
import type { RecommendationDetail, RecommendationListResponse, RecommendationSummary } from "@/types"

/**
 * 获取推荐结果列表（分页 + 用户筛选）。
 * 对应 GET /api/recommendations
 *
 * @param skip  分页偏移量
 * @param limit 每页条数（默认 50）
 * @param userId 可选：按用户 ID 筛选
 */
export const fetchRecommendations = (skip = 0, limit = 50, userId?: string) =>
  request.get<never, RecommendationListResponse>("/recommendations", {
    params: { skip, limit, user_id: userId || undefined },
  })

/**
 * 获取指定用户的所有推荐摘要。
 * 对应 GET /api/recommendations/{userId}
 */
export const fetchUserRecommendations = (userId: string) =>
  request.get<never, RecommendationSummary[]>(`/recommendations/${userId}`)

/**
 * 获取某用户某 session 的推荐详情。
 * 包括历史轨迹、真实目标 POI 和 Top-K 候选列表。
 * 对应 GET /api/recommendations/{userId}/{sessionId}
 */
export const fetchRecommendationDetail = (userId: string, sessionId: string) =>
  request.get<never, RecommendationDetail>(`/recommendations/${userId}/${sessionId}`)
