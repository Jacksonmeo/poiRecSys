/**
 * 密度热力图层（Stage 2 PostGIS）。
 *
 * 独立于 useMap 的图层模块：只负责 source/layer 的注册与数据更新，
 * 生命周期（load/destroy）由 useMap 统一管理。
 * 数据来源：GET /api/analysis/density 的格网密度结果。
 */
import type { GeoJSONSource, Map as MapboxMap } from "mapbox-gl"
import type { DensityCell } from "@/types/spatial"

export const HEATMAP_SOURCE_ID = "density-source"
export const HEATMAP_LAYER_ID = "density-heatmap"

/** 密度格网 GeoJSON 点要素集合（heatmap 图层数据源）。 */
export interface DensityFeatureCollection {
  type: "FeatureCollection"
  features: Array<{
    type: "Feature"
    geometry: { type: "Point"; coordinates: [number, number] }
    properties: { count: number }
  }>
}

/** 密度格网 → GeoJSON 点要素集合。 */
export const buildDensityFeatureCollection = (cells: DensityCell[]): DensityFeatureCollection => ({
  type: "FeatureCollection",
  features: cells.map((cell) => ({
    type: "Feature",
    geometry: { type: "Point", coordinates: [cell.lon, cell.lat] },
    properties: { count: cell.count },
  })),
})

/** 空数据集合：用于图层注册与清空。 */
const emptyDensityCollection = (): DensityFeatureCollection => buildDensityFeatureCollection([])

/** 注册密度热力 source + layer（须在地图 load 之后调用，由 useMap 触发）。 */
export const addHeatmapSource = (map: MapboxMap) => {
  map.addSource(HEATMAP_SOURCE_ID, { type: "geojson", data: emptyDensityCollection() })
  map.addLayer({
    id: HEATMAP_LAYER_ID,
    type: "heatmap",
    source: HEATMAP_SOURCE_ID,
    paint: {
      // count 越高权重越大：0→0，5→1，30→2（封顶，避免极值淹没整体分布）
      "heatmap-weight": ["interpolate", ["linear"], ["get", "count"], 0, 0, 5, 1, 30, 2],
      // 半径随缩放级别增大，缩小时看清整体、放大时看清局部
      "heatmap-radius": ["interpolate", ["linear"], ["zoom"], 0, 12, 9, 22, 14, 40],
      "heatmap-opacity": 0.65,
      // 低密度冷色、高密度暖色，让热点层与浅色地图形成清晰层级。
      "heatmap-color": [
        "interpolate",
        ["linear"],
        ["heatmap-density"],
        0,
        "rgba(43,125,244,0)",
        0.25,
        "rgba(64,184,247,0.32)",
        0.5,
        "rgba(47,224,199,0.5)",
        0.75,
        "rgba(248,218,67,0.68)",
        1,
        "rgba(239,91,66,0.82)",
      ],
    },
  })
}

/** 更新密度数据（cells 为空数组时等价于清空）。 */
export const setHeatmapData = (map: MapboxMap, cells: DensityCell[]) => {
  const source = map.getSource(HEATMAP_SOURCE_ID) as GeoJSONSource | undefined
  source?.setData(buildDensityFeatureCollection(cells))
}

/** 清空密度热力数据。 */
export const clearHeatmapData = (map: MapboxMap) => {
  const source = map.getSource(HEATMAP_SOURCE_ID) as GeoJSONSource | undefined
  source?.setData(emptyDensityCollection())
}
