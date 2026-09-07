import type { GeoJSONSource, Map as MapboxMap } from "mapbox-gl"
import type { AreaFlow, CandidateArea } from "@/types/siteSelection"

export const AREA_FLOW_SOURCE_ID = "area-flows"
export const AREA_FLOW_LAYER_ID = "area-flows-line"
export const AREA_FLOW_ARROW_ID = "area-flows-arrow"

const emptyData = { type: "FeatureCollection" as const, features: [] }

/** 注册区域迁移线和方向箭头图层。 */
export const addAreaFlowLayer = (map: MapboxMap) => {
  if (!map.getSource(AREA_FLOW_SOURCE_ID)) {
    map.addSource(AREA_FLOW_SOURCE_ID, { type: "geojson", data: emptyData })
  }
  if (!map.getLayer(AREA_FLOW_LAYER_ID)) {
    map.addLayer({
      id: AREA_FLOW_LAYER_ID,
      type: "line",
      source: AREA_FLOW_SOURCE_ID,
      paint: {
        "line-color": "#536ee8",
        "line-opacity": 0.66,
        "line-width": ["interpolate", ["linear"], ["get", "flowCount"], 0, 1, 1000, 5],
        "line-dasharray": [2, 1.5],
      },
    })
  }
  if (!map.getLayer(AREA_FLOW_ARROW_ID)) {
    map.addLayer({
      id: AREA_FLOW_ARROW_ID,
      type: "symbol",
      source: AREA_FLOW_SOURCE_ID,
      layout: {
        "symbol-placement": "line",
        "symbol-spacing": 90,
        "text-field": "›",
        "text-size": 18,
        "text-rotation-alignment": "map",
        "text-keep-upright": false,
      },
      paint: { "text-color": "#4058bd", "text-halo-color": "#ffffff", "text-halo-width": 1 },
    })
  }
}

/** 将区域流量按候选区域中心点转换为 LineString。 */
export const setAreaFlowData = (map: MapboxMap, flows: AreaFlow[], areas: CandidateArea[]) => {
  const centers = new Map(areas.filter((area) => area.center).map((area) => [
    area.area_id,
    [area.center!.longitude, area.center!.latitude] as [number, number],
  ]))
  const data = {
    type: "FeatureCollection" as const,
    features: flows.flatMap((flow) => {
      const source = centers.get(flow.source_area)
      const target = centers.get(flow.target_area)
      return source && target ? [{
        type: "Feature" as const,
        geometry: { type: "LineString" as const, coordinates: [source, target] },
        properties: { flowCount: flow.flow_count, source: flow.source_area, target: flow.target_area },
      }] : []
    }),
  }
  ;(map.getSource(AREA_FLOW_SOURCE_ID) as GeoJSONSource | undefined)
    ?.setData(data as Parameters<GeoJSONSource["setData"]>[0])
}
