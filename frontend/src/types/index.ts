/**
 * POI（兴趣点）数据结构。
 * 同时兼容新数据库字段和旧 CSV 字段：
 * - 新字段：venue_id, display_name, venue_category_id, venue_category, latitude, longitude
 * - 旧字段：poi_id, name, category, lng, lat
 */
export interface Poi {
  id: number
  /** Foursquare venue ID（新数据库） */
  venue_id: string
  /** 数据库预填充的展示名称（新，优先级最高） */
  display_name?: string | null
  /** 数据库 venue 类别 ID（新） */
  venue_category_id?: string | null
  /** 数据库 venue 类别名称（新） */
  venue_category?: string | null
  /** 纬度（新数据库字段） */
  latitude: number
  /** 经度（新数据库字段） */
  longitude: number
  /** POI ID（旧 CSV 字段） */
  poi_id: string
  /** POI 名称（旧 CSV 字段） */
  name: string
  /** POI 类别（旧 CSV 字段） */
  category: string
  /** 经度（旧 CSV 字段） */
  lng: number
  /** 纬度（旧 CSV 字段） */
  lat: number
  /** POI 地址 */
  address: string
}

/**
 * 用户轨迹点。
 * 表示用户在某个 session 中访问过的一个签到点，
 * 按 sequence 字段排序后构成完整的轨迹序列。
 */
export interface TrajectoryPoint {
  /** 用户 ID */
  user_id: string
  /** 会话 ID */
  session_id: string
  /** 在轨迹中的顺序号 */
  sequence: number
  /** 访问的 POI ID */
  poi_id: string
  /** 访问的 POI 名称 */
  poi_name: string
  /** 经度 */
  lng: number
  /** 纬度 */
  lat: number
  /** 访问时间 */
  visit_time: string
}

/**
 * 用户摘要信息。
 * 用于用户列表展示，包含用户 ID 及其统计信息。
 */
export interface UserSummary {
  /** 数据库自增 ID（可选） */
  id?: number
  /** 用户唯一标识 */
  user_id: string
  /** 该用户的 session 总数 */
  session_count?: number
  /** 该用户的签到点总数 */
  point_count?: number
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
 * 单个用户的单个 session 及其轨迹点集合。
 */
export interface UserSession {
  /** 用户 ID */
  user_id: string
  /** 会话 ID */
  session_id: string
  /** 该 session 中的所有轨迹点 */
  points: TrajectoryPoint[]
}

/**
 * 用户完整轨迹。
 * 包含用户下的所有 session 及其轨迹数据。
 */
export interface UserTrajectory {
  /** 用户 ID */
  user_id: string
  /** 该用户的所有 session */
  sessions: UserSession[]
}

/**
 * 数据库轨迹点（与 TrajectoryPoint 字段名不同）。
 * 直接对应数据库中的轨迹点记录，使用 snake_case 字段名。
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
 * Session 轨迹响应。
 * 包含 session 元数据和该 session 的所有轨迹点。
 */
export interface SessionTrajectoryResponse {
  /** session 摘要信息 */
  session: SessionSummary
  /** 按 sequence_no 排序的轨迹点数组 */
  points: TrajectoryDbPoint[]
}

/**
 * 推荐结果摘要。
 * 每条记录对应一个已离线生成的推荐 session。
 */
export interface RecommendationSummary {
  /** 用户 ID */
  user_id: string
  /** 会话 ID */
  session_id: string
  /** 真实目标 POI ID（用于评估） */
  target_poi_id: string
  /** 推荐候选数 K */
  top_k: number
}

/**
 * 推荐摘要分页响应。
 * 全量推理后 session 数量较多，前端按页读取，避免一次加载数万条记录。
 */
export interface RecommendationListResponse {
  /** 当前页的推荐摘要列表 */
  items: RecommendationSummary[]
  /** 符合条件的推荐记录总数 */
  total: number
  /** 当前页偏移量 */
  skip: number
  /** 每页条数 */
  limit: number
}

/**
 * 推荐候选 POI。
 * 继承 POI 基础字段，并附加排名和分数信息。
 */
export interface RecommendationCandidate extends Poi {
  /** 候选排名（1-based） */
  rank: number
  /** 推荐分数（用于排序） */
  score: number
}

/**
 * 推荐详情。
 * 包含用户历史轨迹、真实目标 POI 以及 Top-K 候选列表。
 * 用于推荐结果页面的详细展示和地图可视化。
 */
export interface RecommendationDetail {
  /** 用户 ID */
  user_id: string
  /** 会话 ID */
  session_id: string
  /** 历史轨迹点（不包含被留作评估目标的最后一个签到） */
  history: TrajectoryPoint[]
  /** 真实目标 POI */
  target_poi: Poi
  /** Top-K 候选 POI 列表，按 rank 排序 */
  candidates: RecommendationCandidate[]
}

/**
 * 模型评估指标。
 * 记录单个模型在三个核心指标上的表现。
 */
export interface ModelMetric {
  /** 模型名称 */
  model: string
  /** Hit Rate @5，单位 % */
  hr5: number
  /** NDCG @5，单位 % */
  ndcg5: number
  /** MRR @10，单位 % */
  mrr10: number
}
