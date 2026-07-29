import mapboxgl, { type GeoJSONSource, type LngLatBoundsLike, type Map as MapboxMap } from "mapbox-gl"
import type { Ref } from "vue"
import { getPoiDisplayName } from "@/utils/poi"
import type { MapPoint, TrajectoryLayerOptions } from "@/types/map"

const MAPBOX_TOKEN =
  import.meta.env.VITE_MAPBOX_TOKEN ||
  "YOUR_MAPBOX_TOKEN"

const POI_SOURCE_ID = "poi-source"
const POI_LAYER_ID = "poi-points"
const POI_LABEL_LAYER_ID = "poi-labels"
const TRAJECTORY_SOURCE_ID = "trajectory-source"
const TRAJECTORY_LINE_LAYER_ID = "trajectory-line"
const TRAJECTORY_POINT_LAYER_ID = "trajectory-points"
const TRAJECTORY_LABEL_LAYER_ID = "trajectory-labels"

interface PointFeature {
  type: "Feature"
  geometry: { type: "Point"; coordinates: [number, number] }
  properties: Record<string, string | number | boolean>
}

interface LineFeature {
  type: "Feature"
  geometry: { type: "LineString"; coordinates: Array<[number, number]> }
  properties: Record<string, string>
}

interface FeatureCollection<TFeature> {
  type: "FeatureCollection"
  features: TFeature[]
}

type GeoJsonData = Parameters<GeoJSONSource["setData"]>[0]

interface PopupPointFeature {
  geometry: { type: "Point"; coordinates: [number, number] }
  properties?: Record<string, string>
}

const emptyPointCollection = (): FeatureCollection<PointFeature> => ({ type: "FeatureCollection", features: [] })

/**
 * Mapbox 地图渲染逻辑。
 * input: mapElement 为地图 DOM 容器引用，页面传入 POI/轨迹点。
 * output: 图层更新、视角定位和销毁方法。
 * 选用 Mapbox GL 替代 Cesium，避免三维地球和 Entity 系统在看板场景中过重。
 */
export const useMap = (mapElement: Ref<HTMLDivElement | undefined>) => {
  let map: MapboxMap | undefined
  let loaded = false
  const pendingTasks: Array<() => void> = []

  const runWhenReady = (task: () => void) => {
    if (map && loaded) {
      task()
      return
    }
    pendingTasks.push(task)
  }

  const flushPendingTasks = () => {
    pendingTasks.splice(0).forEach((task) => task())
  }

  const getLngLat = (point: MapPoint) => ({
    lng: point.longitude ?? point.lng,
    lat: point.latitude ?? point.lat,
  })

  const isValidPoint = (point: MapPoint) => {
    const { lng, lat } = getLngLat(point)
    return Number.isFinite(lng) && Number.isFinite(lat)
  }

  const colorForCategory = (category?: string | null) => {
    const colors: Record<string, string> = {
      Transport: "#06aed4",
      Shopping: "#f79009",
      Culture: "#7a5af8",
      Park: "#12b76a",
      Landmark: "#fdb022",
      真实目标: "#12b76a",
    }
    return colors[category || ""] ?? "#246bfe"
  }

  const pointFeature = (point: MapPoint, fallbackIndex: number): PointFeature => {
    const { lng, lat } = getLngLat(point)
    const title = getPoiDisplayName(point)
    const category = point.category || point.venue_category || "未知类别"
    return {
      type: "Feature",
      geometry: { type: "Point", coordinates: [lng as number, lat as number] },
      properties: {
        category,
        color: colorForCategory(category),
        id: point.venue_id || point.poi_id || "",
        label: point.rank ? `#${point.rank}` : "",
        rank: point.rank || 0,
        sequenceNo: point.sequence_no || fallbackIndex + 1,
        title,
      },
    }
  }

  const setSourceData = <TFeature>(sourceId: string, data: FeatureCollection<TFeature>) => {
    const source = map?.getSource(sourceId) as GeoJSONSource | undefined
    source?.setData(data as GeoJsonData)
  }

  const clearPoiLayer = () => runWhenReady(() => setSourceData(POI_SOURCE_ID, emptyPointCollection()))

  const clearTrajectoryLayer = () =>
    runWhenReady(() => {
      setSourceData(TRAJECTORY_SOURCE_ID, { type: "FeatureCollection", features: [] })
    })

  const clearMap = () => {
    clearPoiLayer()
    clearTrajectoryLayer()
  }

  const addPoiLayer = (pois: MapPoint[]) =>
    runWhenReady(() => {
      const features = pois.filter(isValidPoint).map(pointFeature)
      setSourceData(POI_SOURCE_ID, { type: "FeatureCollection", features })
    })

  const flyToPoint = (lng: number, lat: number) =>
    runWhenReady(() => {
      map?.flyTo({ center: [lng, lat], duration: 450, essential: false, zoom: 13 })
    })

  const flyToPoints = (points: MapPoint[]) =>
    runWhenReady(() => {
      const validPoints = points.filter(isValidPoint)
      if (!validPoints.length || !map) return
      if (validPoints.length === 1) {
        const { lng, lat } = getLngLat(validPoints[0])
        flyToPoint(lng as number, lat as number)
        return
      }
      const bounds = new mapboxgl.LngLatBounds()
      validPoints.forEach((point) => {
        const { lng, lat } = getLngLat(point)
        bounds.extend([lng as number, lat as number])
      })
      map.fitBounds(bounds as LngLatBoundsLike, { duration: 500, maxZoom: 14, padding: 72 })
    })

  const addTrajectoryLayer = (points: MapPoint[], options: TrajectoryLayerOptions = {}) =>
    runWhenReady(() => {
      const sortedPoints = [...points].filter(isValidPoint).sort((a, b) => (a.sequence_no ?? 0) - (b.sequence_no ?? 0))
      const pointFeatures = sortedPoints.map(pointFeature)
      const coordinates = pointFeatures.map((feature) => feature.geometry.coordinates)
      const lineFeature: LineFeature | undefined =
        coordinates.length > 1
          ? { type: "Feature", geometry: { type: "LineString", coordinates }, properties: { id: options.sessionId || "" } }
          : undefined
      setSourceData(TRAJECTORY_SOURCE_ID, {
        type: "FeatureCollection",
        features: lineFeature ? [lineFeature, ...pointFeatures] : pointFeatures,
      })
      flyToPoints(sortedPoints)
    })

  const addBaseLayers = () => {
    if (!map) return
    map.addSource(POI_SOURCE_ID, { type: "geojson", data: emptyPointCollection() as GeoJsonData })
    map.addSource(TRAJECTORY_SOURCE_ID, { type: "geojson", data: emptyPointCollection() as GeoJsonData })
    map.addLayer({
      id: TRAJECTORY_LINE_LAYER_ID,
      type: "line",
      source: TRAJECTORY_SOURCE_ID,
      filter: ["==", ["geometry-type"], "LineString"],
      paint: { "line-color": "#06aed4", "line-opacity": 0.82, "line-width": 4 },
    })
    map.addLayer({
      id: TRAJECTORY_POINT_LAYER_ID,
      type: "circle",
      source: TRAJECTORY_SOURCE_ID,
      filter: ["==", ["geometry-type"], "Point"],
      paint: { "circle-color": "#06aed4", "circle-radius": 6, "circle-stroke-color": "#ffffff", "circle-stroke-width": 2 },
    })
    map.addLayer({
      id: POI_LAYER_ID,
      type: "circle",
      source: POI_SOURCE_ID,
      paint: { "circle-color": ["get", "color"], "circle-radius": 5, "circle-stroke-color": "#ffffff", "circle-stroke-width": 1 },
    })
    map.addLayer({
      id: POI_LABEL_LAYER_ID,
      type: "symbol",
      source: POI_SOURCE_ID,
      filter: [">", ["get", "rank"], 0],
      layout: { "text-field": ["get", "label"], "text-offset": [0, -1.15], "text-size": 12 },
      paint: { "text-color": "#101828", "text-halo-color": "#ffffff", "text-halo-width": 1.2 },
    })
    map.addLayer({
      id: TRAJECTORY_LABEL_LAYER_ID,
      type: "symbol",
      source: TRAJECTORY_SOURCE_ID,
      filter: ["==", ["geometry-type"], "Point"],
      layout: { "text-field": ["to-string", ["get", "sequenceNo"]], "text-offset": [0, -1.1], "text-size": 11 },
      paint: { "text-color": "#101828", "text-halo-color": "#ffffff", "text-halo-width": 1.1 },
    })
  }

  const bindPopup = () => {
    if (!map) return
    const showPopup = (event: mapboxgl.MapMouseEvent) => {
      const feature = event.features?.[0] as PopupPointFeature | undefined
      if (!feature || feature.geometry.type !== "Point") return
      const coordinates = [...feature.geometry.coordinates] as [number, number]
      const props = feature.properties || {}
      new mapboxgl.Popup({ closeButton: false, maxWidth: "260px" })
        .setLngLat(coordinates)
        .setHTML(`<strong>${props.title || "POI"}</strong><br/><span>${props.category || ""}</span><br/><small>${props.id || ""}</small>`)
        .addTo(map as MapboxMap)
    }
    ;[POI_LAYER_ID, TRAJECTORY_POINT_LAYER_ID].forEach((layerId) => {
      map?.on("click", layerId, showPopup)
      map?.on("mouseenter", layerId, () => {
        if (map) map.getCanvas().style.cursor = "pointer"
      })
      map?.on("mouseleave", layerId, () => {
        if (map) map.getCanvas().style.cursor = ""
      })
    })
  }

  const initMap = () => {
    if (!mapElement.value || map) return
    mapboxgl.accessToken = MAPBOX_TOKEN
    map = new mapboxgl.Map({
      attributionControl: false,
      center: [139.7671, 35.6812],
      container: mapElement.value,
      maxZoom: 18,
      minZoom: 2,
      pitchWithRotate: false,
      style: "mapbox://styles/mapbox/streets-v12",
      zoom: 10,
    })
    map.addControl(new mapboxgl.NavigationControl({ showCompass: false }), "top-right")
    map.on("load", () => {
      loaded = true
      addBaseLayers()
      bindPopup()
      flushPendingTasks()
      map?.resize()
    })
  }

  const destroyMap = () => {
    pendingTasks.length = 0
    loaded = false
    map?.remove()
    map = undefined
  }

  return {
    addPoiLayer,
    addTrajectoryLayer,
    clearMap,
    clearPoiLayer,
    clearTrajectoryLayer,
    destroyMap,
    flyToPoint,
    flyToPoints,
    initMap,
  }
}
