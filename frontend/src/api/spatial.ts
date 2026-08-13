/**
 * 空间分析 API 接口封装（Stage 2 PostGIS）。
 * 对应后端 /api/pois/spatial、/api/pois/nearby、/api/analysis/density。
 * 响应统一由 request 拦截器解包为 data。
 */
import request from "./request"
import type { Bbox, DensityCell, FeatureCollection, NearbyPoi } from "@/types/spatial"

/**
 * bbox 空间查询：返回 GeoJSON FeatureCollection。
 * 对应 GET /api/pois/spatial
 */
export const fetchSpatialPois = (bbox: Bbox, category?: string) =>
  request.get<never, FeatureCollection>("/pois/spatial", {
    params: { ...bbox, category: category || undefined },
  })

/**
 * 半径查询：返回附近 POI 列表（含距离，按距离升序）。
 * 对应 GET /api/pois/nearby
 */
export const fetchNearbyPois = (
  longitude: number,
  latitude: number,
  radiusMeter: number,
  category?: string,
) =>
  request.get<never, NearbyPoi[]>("/pois/nearby", {
    params: { longitude, latitude, radius_meter: radiusMeter, category: category || undefined },
  })

/**
 * 格网密度分析：返回 [{lat, lon, count}]，供 Mapbox heatmap 图层使用。
 * 对应 GET /api/analysis/density
 */
export const fetchDensityGrid = (bbox: Bbox, gridSize: number) =>
  request.get<never, DensityCell[]>("/analysis/density", {
    params: { ...bbox, grid_size: gridSize },
  })
