/**
 * 用户轨迹图层（Stage 5.5 视觉升级）。
 *
 * 负责轨迹 source/layer 的注册，生命周期由 useMap 统一管理。
 * 视觉：轨迹线 glow（line-blur）、空心轨迹点、起点绿点、终点红点（role 属性驱动）、
 * 时序编号标签。
 */
import type { GeoJSONSource, Map as MapboxMap } from "mapbox-gl"

export const TRAJECTORY_SOURCE_ID = "trajectory-source"
export const TRAJECTORY_LINE_LAYER_ID = "trajectory-line"
export const TRAJECTORY_GLOW_LAYER_ID = "trajectory-glow"
export const TRAJECTORY_POINT_LAYER_ID = "trajectory-points"
export const TRAJECTORY_START_LAYER_ID = "trajectory-start"
export const TRAJECTORY_END_LAYER_ID = "trajectory-end"
export const TRAJECTORY_LABEL_LAYER_ID = "trajectory-labels"

type GeoJsonData = Parameters<GeoJSONSource["setData"]>[0]

const emptyCollection = (): GeoJsonData => ({ type: "FeatureCollection", features: [] })

/** 注册轨迹 source。 */
export const addTrajectorySource = (map: MapboxMap) => {
  map.addSource(TRAJECTORY_SOURCE_ID, { type: "geojson", data: emptyCollection() })
}

/** 注册轨迹图层：线 → 空心点 → 起点 → 终点 → 编号标签。 */
export const addTrajectoryLayers = (map: MapboxMap) => {
  map.addLayer({
    id: TRAJECTORY_GLOW_LAYER_ID,
    type: "line",
    source: TRAJECTORY_SOURCE_ID,
    filter: ["==", ["geometry-type"], "LineString"],
    paint: {
      "line-color": "#7c5ce7",
      "line-opacity": 0.28,
      "line-width": 10,
      "line-blur": 5,
    },
  })
  map.addLayer({
    id: TRAJECTORY_LINE_LAYER_ID,
    type: "line",
    source: TRAJECTORY_SOURCE_ID,
    filter: ["==", ["geometry-type"], "LineString"],
    paint: { "line-color": "#805ce9", "line-opacity": 0.92, "line-width": 3.2, "line-dasharray": [1.2, 1.2] },
  })
  map.addLayer({
    id: TRAJECTORY_POINT_LAYER_ID,
    type: "circle",
    source: TRAJECTORY_SOURCE_ID,
    filter: ["==", ["geometry-type"], "Point"],
    paint: {
      "circle-color": "#ffffff",
      "circle-radius": 6,
      "circle-stroke-color": "#8b5cf6",
      "circle-stroke-width": 2.5,
    },
  })
  map.addLayer({
    id: TRAJECTORY_START_LAYER_ID,
    type: "circle",
    source: TRAJECTORY_SOURCE_ID,
    filter: ["==", ["get", "role"], "start"],
    paint: {
      "circle-color": "#16a34a",
      "circle-radius": 7,
      "circle-stroke-color": "#ffffff",
      "circle-stroke-width": 2,
    },
  })
  map.addLayer({
    id: TRAJECTORY_END_LAYER_ID,
    type: "circle",
    source: TRAJECTORY_SOURCE_ID,
    filter: ["==", ["get", "role"], "end"],
    paint: {
      "circle-color": "#dc2626",
      "circle-radius": 7,
      "circle-stroke-color": "#ffffff",
      "circle-stroke-width": 2,
    },
  })
  map.addLayer({
    id: TRAJECTORY_LABEL_LAYER_ID,
    type: "symbol",
    source: TRAJECTORY_SOURCE_ID,
    filter: ["==", ["geometry-type"], "Point"],
    layout: { "text-field": ["to-string", ["get", "sequenceNo"]], "text-offset": [0, -1.2], "text-size": 11 },
    paint: { "text-color": "#101828", "text-halo-color": "#ffffff", "text-halo-width": 1.2 },
  })
}

/** 更新轨迹 source；传入空集合时清空地图轨迹。 */
export const setTrajectoryData = (map: MapboxMap, data: GeoJsonData) => {
  const source = map.getSource(TRAJECTORY_SOURCE_ID) as GeoJSONSource | undefined
  source?.setData(data)
}
