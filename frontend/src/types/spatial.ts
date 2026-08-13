/**
 * 空间分析相关类型（Stage 2 PostGIS）。
 * 与后端 schemas/spatial.py 一一对应。
 */

/** WGS84 包围盒。 */
export interface Bbox {
  min_lon: number
  min_lat: number
  max_lon: number
  max_lat: number
}

/** 密度格网单元：格点中心坐标 + 格内 POI 数量（供 Mapbox heatmap 使用）。 */
export interface DensityCell {
  lat: number
  lon: number
  count: number
}

/** 半径查询结果：POI 基本信息 + 距查询中心点的距离（米）。 */
export interface NearbyPoi {
  venue_id: string
  display_name: string | null
  venue_category: string | null
  latitude: number
  longitude: number
  distance_m: number
}

/** 空间查询的 GeoJSON Feature（RFC 7946 子集）。 */
export interface PoiFeature {
  type: "Feature"
  geometry: { type: "Point"; coordinates: [number, number] }
  properties: { venue_id: string; category: string | null; name: string | null }
}

/** 空间查询的 GeoJSON FeatureCollection。 */
export interface FeatureCollection {
  type: "FeatureCollection"
  features: PoiFeature[]
}
