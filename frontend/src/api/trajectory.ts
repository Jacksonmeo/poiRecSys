/**
 * 用户轨迹相关 API 接口封装。
 * 对应后端 /api/users 和 /api/sessions 路由组。
 */
import request from "./request"
import type {
  SessionListResponse,
  SessionTrajectoryResponse,
  UserListResponse,
  UserSummary,
} from "@/types"

/**
 * 用户查询参数。
 * 支持按关键词模糊搜索（用于远程搜索下拉框），以及分页。
 */
export interface UserQueryParams {
  /** 搜索关键词，按 user_id 模糊匹配 */
  keyword?: string
  /** 分页偏移量 */
  skip?: number
  /** 每页条数 */
  limit?: number
}

/**
 * 获取用户列表（分页 + 关键词搜索）。
 * 对应 GET /api/users
 */
export const getUsers = (params: UserQueryParams = {}) =>
  request.get<never, UserListResponse>("/users", { params })

/**
 * 获取指定用户的 session 列表。
 * 用户 ID 通过 URL 编码防止特殊字符导致路由错误。
 * 对应 GET /api/users/{userId}/sessions
 */
export const getUserSessions = (
  userId: string,
  params?: {
    skip?: number
    limit?: number
  },
) => request.get<never, SessionListResponse>(`/users/${encodeURIComponent(userId)}/sessions`, { params })

/**
 * 获取指定 session 的完整轨迹点列表。
 * 对应 GET /api/sessions/{sessionId}/trajectory
 */
export const getSessionTrajectory = (sessionId: string) =>
  request.get<never, SessionTrajectoryResponse>(`/sessions/${encodeURIComponent(sessionId)}/trajectory`)

/**
 * 便捷方法：直接获取用户摘要列表（前 20 条）。
 * 封装了 getUsers 的分页逻辑，避免调用方重复传参。
 */
export const fetchUsers = async (): Promise<UserSummary[]> => {
  const result = await getUsers({ skip: 0, limit: 20 })
  return result.items
}
