/**
 * POI（兴趣点）数据结构。
 * 第一阶段治理后统一使用数据库原生字段：venue_id / display_name / venue_category / latitude / longitude。
 * 旧 CSV 兼容字段（poi_id / name / category / lng / lat / address）已全部移除。
 */
export interface Poi {
  id: number
  /** Foursquare venue ID（业务主键） */
  venue_id: string
  /** 数据库预填充的展示名称（可空） */
  display_name?: string | null
  /** Foursquare venue 类别 ID */
  venue_category_id?: string | null
  /** 人类可读的类别名称 */
  venue_category?: string | null
  /** 纬度 */
  latitude: number
  /** 经度 */
  longitude: number
}

/**
 * 数据库轨迹点。
 * 对应 /api/sessions/{sid}/trajectory 与推荐详情 history 中的轨迹点结构。
 */
export interface TrajectoryDbPoint {
  /** 在轨迹中的序号 */
  sequence_no: number
  /** Foursquare venue ID */
  venue_id: string
  /** 展示名称（可能为空） */
  display_name?: string | null
  /** venue 类别（可能为空） */
  venue_category?: string | null
  /** 经度 */
  longitude: number
  /** 纬度 */
  latitude: number
  /** UTC 时间戳 */
  utc_timestamp: string
}

/**
 * 用户摘要信息。
 * 用于用户列表展示。
 */
export interface UserSummary {
  /** 数据库自增 ID（可选） */
  id?: number
  /** 用户唯一标识 */
  user_id: string
}

/**
 * 用户列表分页响应。
 * 由于用户数量可能很大，前端按页读取。
 */
export interface UserListResponse {
  /** 当前页的用户摘要列表 */
  items: UserSummary[]
  /** 符合条件的用户总数 */
  total: number
  /** 当前页偏移量 */
  skip: number
  /** 每页条数 */
  limit: number
}

/**
 * 会话摘要信息。
 * 包含 session 的基本元数据，用于 session 选择列表。
 */
export interface SessionSummary {
  /** 会话唯一标识 */
  session_id: string
  /** 所属用户 ID */
  user_id: string
  /** 会话开始时间 */
  start_time: string
  /** 会话结束时间 */
  end_time: string
  /** 该 session 中的签到点数量 */
  checkin_count: number
  /** 数据集来源标识 */
  dataset: string
}

/**
 * 会话列表分页响应。
 * 按用户查询其下的 session 列表。
 */
export interface SessionListResponse {
  /** 当前页的会话摘要列表 */
  items: SessionSummary[]
  /** 符合条件的会话总数 */
  total: number
  /** 当前页偏移量 */
  skip: number
  /** 每页条数 */
  limit: number
}

/**
 * Session 轨迹响应。
 * 包含 session 元数据和该 session 的所有轨迹点。
 */
export interface SessionTrajectoryResponse {
  /** session 摘要信息 */
  session: SessionSummary
  /** 按 sequence_no 排序的轨迹点数组 */
  points: TrajectoryDbPoint[]
}
