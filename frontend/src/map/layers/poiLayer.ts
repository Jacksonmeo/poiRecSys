/**
 * POI 点位图层（Stage 5.5 视觉升级）。
 *
 * 负责 POI source/layer 的注册与数据更新，生命周期由 useMap 统一管理。
 * 视觉：rank=1 光晕焦点、半径分级（rank 1→10px / 2-3→8px / 其他 6px）、
 * hover 放大（feature-state 驱动）、排名标签。
 */
import type { GeoJSONSource, Map as MapboxMap } from "mapbox-gl"

export const POI_SOURCE_ID = "poi-source"
export const POI_LAYER_ID = "poi-points"
export const POI_LABEL_LAYER_ID = "poi-labels"
export const POI_HALO_LAYER_ID = "poi-halo"

type GeoJsonData = Parameters<GeoJSONSource["setData"]>[0]

/** 空点集合：用于图层注册与清空。 */
const emptyCollection = (): GeoJsonData => ({ type: "FeatureCollection", features: [] })

/** 半径分级表达式：rank<1 → 6；rank 1 → 10；rank 2-3 → 8；rank≥4 → 6。 */
const radiusByRank = [
  "step",
  ["get", "rank"],
  6,
  1,
  10,
  2,
  8,
  4,
  6,
]

/** 注册 POI source（promoteId 以 properties.id 作为 feature id，供 hover feature-state 使用）。 */
export const addPoiSource = (map: MapboxMap) => {
  map.addSource(POI_SOURCE_ID, { type: "geojson", data: emptyCollection(), promoteId: "id" })
}

/** 注册 POI 图层：光晕（rank=1）→ 点位（hover 放大）→ 排名标签。 */
export const addPoiLayers = (map: MapboxMap) => {
  map.addLayer({
    id: POI_HALO_LAYER_ID,
    type: "circle",
    source: POI_SOURCE_ID,
    filter: ["==", ["get", "rank"], 1],
    paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 7, 15, 14, 22],
      "circle-color": "#805ce9",
      "circle-opacity": 0.2,
      "circle-blur": 0.25,
    },
  })
  map.addLayer({
    id: POI_LAYER_ID,
    type: "circle",
    source: POI_SOURCE_ID,
    paint: {
      "circle-radius": [
        "case",
        ["boolean", ["feature-state", "hover"], false],
        ["+", radiusByRank, 4],
        radiusByRank,
      ],
      "circle-color": ["case", [">", ["get", "rank"], 0], "#7658e7", ["get", "color"]],
      "circle-stroke-color": "#ffffff",
      "circle-stroke-width": ["case", [">", ["get", "rank"], 0], 2.5, 1.5],
    },
  })
  map.addLayer({
    id: POI_LABEL_LAYER_ID,
    type: "symbol",
    source: POI_SOURCE_ID,
    filter: [">", ["get", "rank"], 0],
    layout: { "text-field": ["get", "label"], "text-offset": [0, -1.25], "text-size": 13 },
    paint: { "text-color": "#101828", "text-halo-color": "#ffffff", "text-halo-width": 1.3 },
  })
}

/** 更新 POI 数据（空集合等价于清空）。 */
export const setPoiData = (map: MapboxMap, data: GeoJsonData) => {
  const source = map.getSource(POI_SOURCE_ID) as GeoJSONSource | undefined
  source?.setData(data)
}

/** 通过写入空集合清除当前 POI source。 */
export const clearPoiData = (map: MapboxMap) => {
  setPoiData(map, emptyCollection())
}
