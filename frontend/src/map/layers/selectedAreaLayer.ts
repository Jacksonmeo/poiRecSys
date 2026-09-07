import type { Map as MapboxMap } from "mapbox-gl"
import { CANDIDATE_AREA_SOURCE_ID } from "./candidateAreaLayer"

export const SELECTED_AREA_FILL_ID = "selected-area-fill"
export const SELECTED_AREA_OUTLINE_ID = "selected-area-outline"

/** 注册用于高亮当前候选区域的覆盖图层。 */
export const addSelectedAreaLayers = (map: MapboxMap) => {
  const filter: mapboxgl.FilterSpecification = ["==", ["get", "areaId"], ""]
  if (!map.getLayer(SELECTED_AREA_FILL_ID)) {
    map.addLayer({
      id: SELECTED_AREA_FILL_ID,
      type: "fill",
      source: CANDIDATE_AREA_SOURCE_ID,
      filter,
      paint: { "fill-color": ["get", "color"], "fill-opacity": 0.34 },
    })
  }
  if (!map.getLayer(SELECTED_AREA_OUTLINE_ID)) {
    map.addLayer({
      id: SELECTED_AREA_OUTLINE_ID,
      type: "line",
      source: CANDIDATE_AREA_SOURCE_ID,
      filter,
      paint: { "line-color": "#ffffff", "line-width": 4, "line-opacity": 0.95 },
    })
  }
}

/** 更新高亮图层过滤器，使地图与当前选中区域同步。 */
export const selectAreaOnMap = (map: MapboxMap, areaId: string | null) => {
  const filter: mapboxgl.FilterSpecification = ["==", ["get", "areaId"], areaId ?? ""]
  map.setFilter(SELECTED_AREA_FILL_ID, filter)
  map.setFilter(SELECTED_AREA_OUTLINE_ID, filter)
}
