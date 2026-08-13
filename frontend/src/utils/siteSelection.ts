import type { AreaMetric, CandidateArea, SiteSelectionArtifact } from "@/types/siteSelection"

const EARTH_RADIUS_M = 6_371_008.8
const AREA_RADIUS_M = 1_000

const AREA_CATALOG: Record<string, { center: [number, number]; color: string }> = {
  shinjuku: { center: [139.700464, 35.689729], color: "#4967f2" },
  shibuya: { center: [139.701636, 35.658034], color: "#11a7c7" },
  ginza: { center: [139.765, 35.6717], color: "#e69632" },
  ikebukuro: { center: [139.7109, 35.729503], color: "#8b5cf6" },
}

export const METRIC_META: Record<string, { label: string; unit: string }> = {
  poi_count: { label: "POI 总量", unit: "个" },
  competitor_count: { label: "竞品门店", unit: "个" },
  transport_poi_count: { label: "交通设施", unit: "个" },
  business_mix_diversity: { label: "业态多样性", unit: "类" },
  historical_checkin_count: { label: "历史签到", unit: "次" },
  unique_user_count: { label: "历史用户", unit: "人" },
}

/** 根据中心点、方位角和固定半径计算圆周上的一个经纬度。 */
const destination = (center: [number, number], bearing: number): [number, number] => {
  const [longitude, latitude] = center
  const angularDistance = AREA_RADIUS_M / EARTH_RADIUS_M
  const lat1 = latitude * Math.PI / 180
  const lon1 = longitude * Math.PI / 180
  const angle = bearing * Math.PI / 180
  const lat2 = Math.asin(
    Math.sin(lat1) * Math.cos(angularDistance)
      + Math.cos(lat1) * Math.sin(angularDistance) * Math.cos(angle),
  )
  const lon2 = lon1 + Math.atan2(
    Math.sin(angle) * Math.sin(angularDistance) * Math.cos(lat1),
    Math.cos(angularDistance) - Math.sin(lat1) * Math.sin(lat2),
  )
  return [lon2 * 180 / Math.PI, lat2 * 180 / Math.PI]
}

/** 用 64 个采样点生成候选区域的近似圆形 Polygon。 */
const circlePolygon = (center: [number, number]) => ({
  type: "Polygon" as const,
  coordinates: [Array.from({ length: 65 }, (_, index) => destination(center, index * 360 / 64))],
})

/** 为缺少中心点或 Polygon 的候选区域补齐地图渲染所需的几何信息。 */
export const enrichCandidateAreas = (areas: CandidateArea[]): CandidateArea[] => areas.map((area) => {
  if (area.center && area.polygon) return area
  const catalog = AREA_CATALOG[area.area_id]
  if (!catalog) return area
  return {
    ...area,
    center: { longitude: catalog.center[0], latitude: catalog.center[1] },
    polygon: circlePolygon(catalog.center),
  }
})

/** 返回候选区域在地图和证据面板中使用的稳定颜色。 */
export const areaColor = (areaId: string) => AREA_CATALOG[areaId]?.color ?? "#64748b"

/** 将 artifact 指标按区域归组，兼容带 area_id 与旧式顺序指标两种格式。 */
export const metricsByArea = (artifact: SiteSelectionArtifact): Record<string, AreaMetric[]> => {
  const grouped: Record<string, AreaMetric[]> = Object.fromEntries(
    artifact.candidate_areas.map((area) => [area.area_id, []]),
  )
  const explicit = artifact.metrics.every((metric) => Boolean(metric.area_id))
  if (explicit) {
    artifact.metrics.forEach((metric) => {
      if (metric.area_id) grouped[metric.area_id]?.push(metric)
    })
    return grouped
  }
  const size = artifact.candidate_areas.length
    ? Math.floor(artifact.metrics.length / artifact.candidate_areas.length)
    : 0
  artifact.candidate_areas.forEach((area, index) => {
    grouped[area.area_id] = artifact.metrics.slice(index * size, (index + 1) * size)
      .map((metric) => ({ ...metric, area_id: area.area_id }))
  })
  return grouped
}

/** 将指标 id 转为面向用户的中文名称。 */
export const metricLabel = (metricId: string) => METRIC_META[metricId]?.label ?? metricId

/** 返回指标单位，优先使用 artifact 自带单位。 */
export const metricUnit = (metric: AreaMetric) => metric.unit ?? METRIC_META[metric.metric_id]?.unit ?? ""
