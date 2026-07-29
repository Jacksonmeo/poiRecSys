/**
 * 地图点位的兼容结构。
 * input: POI、轨迹点、推荐候选等不同接口的经纬度字段。
 * output: Mapbox 图层渲染需要的统一点位模型。
 */
export interface MapPoint {
  lng?: number
  lat?: number
  longitude?: number
  latitude?: number
  name?: string
  category?: string
  rank?: number
  score?: number
  display_name?: string | null
  venue_id?: string
  venue_category?: string | null
  poi_id?: string
  sequence_no?: number
  utc_timestamp?: string
}

export interface TrajectoryLayerOptions {
  sessionId?: string
}
