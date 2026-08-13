import mapboxgl, { type LngLatBoundsLike, type Map as MapboxMap } from "mapbox-gl"
import type { Ref } from "vue"
import { getPoiDisplayName } from "@/utils/poi"
import type { MapPoint, TrajectoryLayerOptions } from "@/types/map"
import type { DensityCell } from "@/types/spatial"
import { addHeatmapSource, clearHeatmapData, setHeatmapData } from "@/map/layers/heatmapLayer"
import { POI_LAYER_ID, POI_SOURCE_ID, addPoiLayers, addPoiSource, clearPoiData, setPoiData } from "@/map/layers/poiLayer"
import {
  TRAJECTORY_POINT_LAYER_ID,
  addTrajectoryLayers,
  addTrajectorySource,
  setTrajectoryData,
} from "@/map/layers/trajectoryLayer"
import {
  CANDIDATE_AREA_FILL_ID,
  addCandidateAreaLayers,
  setCandidateAreaData,
} from "@/map/layers/candidateAreaLayer"
import { addAreaFlowLayer, setAreaFlowData } from "@/map/layers/areaFlowLayer"
import { addSelectedAreaLayers, selectAreaOnMap } from "@/map/layers/selectedAreaLayer"
import type { AreaFlow, CandidateArea } from "@/types/siteSelection"

// Mapbox Token 只从环境变量读取（frontend/.env），严禁硬编码进源码。
const MAPBOX_TOKEN: string | undefined = import.meta.env.VITE_MAPBOX_TOKEN

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

interface PopupPointFeature {
  id?: string | number
  geometry: { type: "Point"; coordinates: [number, number] }
  properties?: Record<string, string | number | boolean>
}

/**
 * Mapbox 地图渲染逻辑（Stage 5.5 视觉升级）。
 * input: mapElement 为地图 DOM 容器引用，页面传入 POI/轨迹点。
 * output: 图层更新、视角定位和销毁方法。
 * 图层注册委托 map/layers/ 模块；本文件只保留生命周期、数据转换与交互绑定。
 */
export const useMap = (
  mapElement: Ref<HTMLDivElement | undefined>,
  options: { onAreaSelect?: (areaId: string) => void } = {},
) => {
  let map: MapboxMap | undefined
  let loaded = false
  let hoveredFeatureId: string | number | undefined
  const pendingTasks: Array<() => void> = []

  /** 地图尚未 load 时暂存操作，地图 ready 后立即执行。 */
  const runWhenReady = (task: () => void) => {
    if (map && loaded) {
      task()
      return
    }
    pendingTasks.push(task)
  }

  /** 执行并清空地图初始化期间积压的操作。 */
  const flushPendingTasks = () => {
    pendingTasks.splice(0).forEach((task) => task())
  }

  /** 将业务 MapPoint 转成 Mapbox flyTo 使用的经纬度对象。 */
  const getLngLat = (point: MapPoint) => ({
    lng: point.longitude,
    lat: point.latitude,
  })

  /** 检查点位经纬度是否为可用于地图渲染的有限数字。 */
  const isValidPoint = (point: MapPoint) => {
    const { lng, lat } = getLngLat(point)
    return Number.isFinite(lng) && Number.isFinite(lat)
  }

  /** 分类色板：只属于地图（POI 类别语义色），与 UI 品牌色解耦。 */
  const colorForCategory = (category?: string | null) => {
    const colors: Record<string, string> = {
      Transport: "#06aed4",
      Shopping: "#f79009",
      Culture: "#7a5af8",
      Park: "#12b76a",
      Landmark: "#fdb022",
      真实目标: "#12b76a",
    }
    return colors[category || ""] ?? "#2563eb"
  }

  /** 将一个 POI 转换成地图点 Feature，并补充展示属性。 */
  const pointFeature = (point: MapPoint, fallbackIndex: number): PointFeature => {
    const { lng, lat } = getLngLat(point)
    const title = getPoiDisplayName(point)
    const category = point.venue_category || "未知类别"
    return {
      type: "Feature",
      geometry: { type: "Point", coordinates: [lng as number, lat as number] },
      properties: {
        category,
        color: colorForCategory(category),
        id: point.venue_id || "",
        label: point.rank ? `#${point.rank}` : "",
        rank: point.rank || 0,
        sequenceNo: point.sequence_no || fallbackIndex + 1,
        title,
      },
    }
  }

  /** 清空 POI 图层。 */
  const clearPoiLayer = () => runWhenReady(() => map && clearPoiData(map))

  /** 清空轨迹图层。 */
  const clearTrajectoryLayer = () =>
    runWhenReady(() => {
      if (map) setTrajectoryData(map, { type: "FeatureCollection", features: [] })
    })

  /** 同时清空 POI 与轨迹，供页面切换数据时复用。 */
  const clearMap = () => {
    clearPoiLayer()
    clearTrajectoryLayer()
  }

  /** 写入候选区域 Polygon，并在地图 ready 后执行。 */
  const setCandidateAreas = (areas: CandidateArea[]) => runWhenReady(() => {
    if (map) setCandidateAreaData(map, areas)
  })

  /** 写入候选区域之间的迁移关系。 */
  const setAreaFlows = (flows: AreaFlow[], areas: CandidateArea[]) => runWhenReady(() => {
    if (map) setAreaFlowData(map, flows, areas)
  })

  /** 更新地图上的当前候选区域高亮状态。 */
  const selectCandidateArea = (areaId: string | null) => runWhenReady(() => {
    if (map) selectAreaOnMap(map, areaId)
  })

  /** 计算所有候选区域的边界，并调整视野使其完整可见。 */
  const flyToCandidateAreas = (areas: CandidateArea[]) => runWhenReady(() => {
    const coordinates = areas.flatMap((area) => {
      const ring = area.polygon?.coordinates[0]
      if (ring?.length) return ring.map(([lng, lat]) => [lng, lat] as [number, number])
      return area.center ? [[area.center.longitude, area.center.latitude] as [number, number]] : []
    })
    if (!map || !coordinates.length) return
    const bounds = new mapboxgl.LngLatBounds()
    coordinates.forEach((coordinate) => bounds.extend(coordinate))
    map.fitBounds(bounds as LngLatBoundsLike, { duration: 500, maxZoom: 12.6, padding: 70 })
  })

  /** 过滤无效点位、写入 POI 数据并刷新点图层。 */
  const addPoiLayer = (pois: MapPoint[]) =>
    runWhenReady(() => {
      const features = pois.filter(isValidPoint).map(pointFeature)
      if (map) setPoiData(map, { type: "FeatureCollection", features })
    })

  /** 将地图镜头平滑移动到单个经纬度。 */
  const flyToPoint = (lng: number, lat: number) =>
    runWhenReady(() => {
      map?.flyTo({ center: [lng, lat], duration: 450, essential: false, zoom: 13 })
    })

  /** 将镜头移动到多个点位；单点使用 flyTo，多点使用 fitBounds。 */
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

  /** 写入密度格网数据，驱动热力图层。 */
  const setDensityLayer = (cells: DensityCell[]) => {
    runWhenReady(() => {
      if (map) setHeatmapData(map, cells)
    })
  }

  /** 清空密度热力图 source。 */
  const clearDensityLayer = () => {
    runWhenReady(() => {
      if (map) clearHeatmapData(map)
    })
  }

  /** 按时序写入用户轨迹，并自动调整地图视野。 */
  const addTrajectoryLayer = (points: MapPoint[], options: TrajectoryLayerOptions = {}) =>
    runWhenReady(() => {
      const sortedPoints = [...points].filter(isValidPoint).sort((a, b) => (a.sequence_no ?? 0) - (b.sequence_no ?? 0))
      const pointFeatures = sortedPoints.map(pointFeature)
      // 首尾语义：起点绿点、终点红点（role 属性驱动专用图层）
      if (pointFeatures.length > 0) {
        pointFeatures[0].properties.role = "start"
        if (pointFeatures.length > 1) pointFeatures[pointFeatures.length - 1].properties.role = "end"
      }
      const coordinates = pointFeatures.map((feature) => feature.geometry.coordinates)
      const lineFeature: LineFeature | undefined =
        coordinates.length > 1
          ? { type: "Feature", geometry: { type: "LineString", coordinates }, properties: { id: options.sessionId || "" } }
          : undefined
      if (map) {
        setTrajectoryData(map, {
          type: "FeatureCollection",
          features: lineFeature ? [lineFeature, ...pointFeatures] : pointFeatures,
        })
      }
      flyToPoints(sortedPoints)
    })

  /** 在地图 load 后一次性注册所有业务 source 与 layer。 */
  const addBaseLayers = () => {
    if (!map) return
    addPoiSource(map)
    addTrajectorySource(map)
    addHeatmapSource(map)
    addPoiLayers(map)
    addTrajectoryLayers(map)
    addCandidateAreaLayers(map)
    addAreaFlowLayer(map)
    addSelectedAreaLayers(map)
  }

  /** 绑定点击 popup 与 hover 交互（POI 点位 hover 放大 + 指针反馈）。 */
  const bindInteractions = () => {
    if (!map) return
    /** 为 POI 或轨迹点创建统一的信息弹窗。 */
    const showPopup = (event: mapboxgl.MapMouseEvent) => {
      const feature = event.features?.[0] as PopupPointFeature | undefined
      if (!feature || feature.geometry.type !== "Point") return
      const [lng, lat] = feature.geometry.coordinates as [number, number]
      const props = feature.properties || {}
      const rank = props.rank ? ` · #${props.rank}` : ""
      new mapboxgl.Popup({ closeButton: false, maxWidth: "260px", offset: 10 })
        .setLngLat([lng, lat])
        .setHTML(
          `<div class="map-popup"><strong>${props.title || "POI"}</strong>` +
            `<span class="map-popup__category">${props.category || ""}${rank}</span>` +
            `<small>${lng.toFixed(5)}, ${lat.toFixed(5)}</small></div>`,
        )
        .addTo(map as MapboxMap)
    }
    map.on("click", POI_LAYER_ID, showPopup)
    map.on("click", TRAJECTORY_POINT_LAYER_ID, showPopup)
    map.on("mouseenter", POI_LAYER_ID, (event) => {
      const feature = event.features?.[0] as PopupPointFeature | undefined
      if (feature && feature.id != null) {
        hoveredFeatureId = feature.id
        map?.setFeatureState({ source: POI_SOURCE_ID, id: feature.id }, { hover: true })
      }
      map?.getCanvas().style.setProperty("cursor", "pointer")
    })
    map.on("mouseleave", POI_LAYER_ID, () => {
      if (hoveredFeatureId != null) {
        map?.setFeatureState({ source: POI_SOURCE_ID, id: hoveredFeatureId }, { hover: false })
      }
      hoveredFeatureId = undefined
      map?.getCanvas().style.setProperty("cursor", "")
    })
    map.on("click", CANDIDATE_AREA_FILL_ID, (event) => {
      const feature = event.features?.[0] as { properties?: Record<string, unknown> } | undefined
      const areaId = feature?.properties?.areaId
      if (typeof areaId === "string") options.onAreaSelect?.(areaId)
    })
    map.on("mouseenter", CANDIDATE_AREA_FILL_ID, () => {
      map?.getCanvas().style.setProperty("cursor", "pointer")
    })
    map.on("mouseleave", CANDIDATE_AREA_FILL_ID, () => {
      map?.getCanvas().style.setProperty("cursor", "")
    })
  }

  /** 创建 Mapbox 实例并绑定 load 生命周期。 */
  const initMap = () => {
    if (!mapElement.value || map) return
    if (!MAPBOX_TOKEN) {
      console.error("[useMap] 缺少 VITE_MAPBOX_TOKEN，请在 frontend/.env 中配置后重启 dev server。")
      return
    }
    mapboxgl.accessToken = MAPBOX_TOKEN
    map = new mapboxgl.Map({
      attributionControl: false,
      center: [139.7671, 35.6812],
      container: mapElement.value,
      maxZoom: 18,
      minZoom: 2,
      pitchWithRotate: false,
      // light-v11：克制的浅色底图，减少街道噪声，地图作为结果画布
      style: "mapbox://styles/mapbox/light-v11",
      zoom: 10.6,
    })
    map.addControl(new mapboxgl.NavigationControl({ showCompass: false }), "top-right")
    map.on("load", () => {
      loaded = true
      addBaseLayers()
      bindInteractions()
      flushPendingTasks()
      map?.resize()
    })
  }

  /** 移除 Mapbox 实例并清空尚未执行的任务。 */
  const destroyMap = () => {
    pendingTasks.length = 0
    loaded = false
    hoveredFeatureId = undefined
    map?.remove()
    map = undefined
  }

  /** 在容器尺寸变化后通知 Mapbox 重排画布。 */
  const resizeMap = () => {
    map?.resize()
  }

  return {
    addPoiLayer,
    addTrajectoryLayer,
    clearDensityLayer,
    clearMap,
    clearPoiLayer,
    clearTrajectoryLayer,
    destroyMap,
    flyToPoint,
    flyToPoints,
    flyToCandidateAreas,
    initMap,
    resizeMap,
    selectCandidateArea,
    setAreaFlows,
    setCandidateAreas,
    setDensityLayer,
  }
}
