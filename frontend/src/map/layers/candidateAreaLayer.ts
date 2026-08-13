import type { GeoJSONSource, Map as MapboxMap } from "mapbox-gl"
import type { CandidateArea } from "@/types/siteSelection"
import { areaColor } from "@/utils/siteSelection"

export const CANDIDATE_AREA_SOURCE_ID = "candidate-areas"
export const CANDIDATE_AREA_FILL_ID = "candidate-areas-fill"
export const CANDIDATE_AREA_OUTLINE_ID = "candidate-areas-outline"

const emptyData = { type: "FeatureCollection" as const, features: [] }

/** 注册候选区域 GeoJSON source、填充层和轮廓层。 */
export const addCandidateAreaLayers = (map: MapboxMap) => {
  if (!map.getSource(CANDIDATE_AREA_SOURCE_ID)) {
    map.addSource(CANDIDATE_AREA_SOURCE_ID, { type: "geojson", data: emptyData })
  }
  if (!map.getLayer(CANDIDATE_AREA_FILL_ID)) {
    map.addLayer({
      id: CANDIDATE_AREA_FILL_ID,
      type: "fill",
      source: CANDIDATE_AREA_SOURCE_ID,
      paint: {
        "fill-color": ["get", "color"],
        "fill-opacity": 0.16,
      },
    })
  }
  if (!map.getLayer(CANDIDATE_AREA_OUTLINE_ID)) {
    map.addLayer({
      id: CANDIDATE_AREA_OUTLINE_ID,
      type: "line",
      source: CANDIDATE_AREA_SOURCE_ID,
      paint: { "line-color": ["get", "color"], "line-width": 1.5, "line-opacity": 0.8 },
    })
  }
}

/** 将候选区域 Polygon 转换为地图 source 数据。 */
export const setCandidateAreaData = (map: MapboxMap, areas: CandidateArea[]) => {
  const data = {
    type: "FeatureCollection" as const,
    features: areas.filter((area) => area.polygon).map((area) => ({
      type: "Feature",
      geometry: area.polygon!,
      properties: { areaId: area.area_id, color: areaColor(area.area_id), name: area.display_name },
    })),
  }
  ;(map.getSource(CANDIDATE_AREA_SOURCE_ID) as GeoJSONSource | undefined)
    ?.setData(data as Parameters<GeoJSONSource["setData"]>[0])
}
