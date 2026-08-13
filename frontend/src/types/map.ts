/**
 * 地图点位的兼容结构。
 * 第一阶段治理后统一使用 longitude / latitude / venue_id / display_name / venue_category，
 * 移除旧 CSV 字段（lng / lat / poi_id / name / category）。
 * 所有字段可选，便于不同接口来源的点位直接传入地图层。
 */
export interface MapPoint {
  longitude?: number
  latitude?: number
  venue_id?: string
  display_name?: string | null
  venue_category?: string | null
  /** 推荐排名（有值时地图叠加排名标签） */
  rank?: number
  /** 推荐分数 */
  score?: number
  /** Agent 推荐工具返回的可解释理由。 */
  reason?: string | null
  /** 轨迹点顺序号 */
  sequence_no?: number
  /** 签到时间戳 */
  utc_timestamp?: string
}

export interface TrajectoryLayerOptions {
  sessionId?: string
}
