<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue"
import "mapbox-gl/dist/mapbox-gl.css"
import { useMap } from "@/composables/useMap"
import type { MapPoint, TrajectoryLayerOptions } from "@/types/map"
import type { DensityCell } from "@/types/spatial"
import type { AreaFlow, CandidateArea } from "@/types/siteSelection"

const mapElement = ref<HTMLDivElement>()
const emit = defineEmits<{ selectArea: [areaId: string] }>()
const map = useMap(mapElement, { onAreaSelect: (areaId) => emit("selectArea", areaId) })
let resizeObserver: ResizeObserver | undefined
let resizeFrame: number | undefined

/** 合并连续尺寸变化，只在下一帧通知 Mapbox resize，避免重复布局。 */
const scheduleMapResize = () => {
  if (resizeFrame !== undefined) window.cancelAnimationFrame(resizeFrame)
  resizeFrame = window.requestAnimationFrame(() => {
    map.resizeMap()
    resizeFrame = undefined
  })
}

/**
 * Mapbox 地图容器组件。
 * input: 父组件通过 expose 调用图层方法并传入点位数据。
 * output: 稳定的二维地图 DOM 与轻量 Mapbox GL 实例。
 * 页面不直接操作地图 SDK，方便后续继续拆 PoiLayer/TrajectoryLayer。
 */
onMounted(() => {
  map.initMap()
  if (mapElement.value) {
    resizeObserver = new ResizeObserver(scheduleMapResize)
    resizeObserver.observe(mapElement.value)
  }
})
onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  if (resizeFrame !== undefined) window.cancelAnimationFrame(resizeFrame)
  map.destroyMap()
})

defineExpose<{
  addPoiLayer: (points: MapPoint[]) => void
  addTrajectoryLayer: (points: MapPoint[], options?: TrajectoryLayerOptions) => void
  clearDensityLayer: () => void
  clearMap: () => void
  clearPoiLayer: () => void
  clearTrajectoryLayer: () => void
  flyToPoint: (lng: number, lat: number) => void
  flyToPoints: (points: MapPoint[]) => void
  flyToCandidateAreas: (areas: CandidateArea[]) => void
  resizeMap: () => void
  selectCandidateArea: (areaId: string | null) => void
  setAreaFlows: (flows: AreaFlow[], areas: CandidateArea[]) => void
  setCandidateAreas: (areas: CandidateArea[]) => void
  setDensityLayer: (cells: DensityCell[]) => void
}>({
  addPoiLayer: map.addPoiLayer,
  addTrajectoryLayer: map.addTrajectoryLayer,
  clearDensityLayer: map.clearDensityLayer,
  clearMap: map.clearMap,
  clearPoiLayer: map.clearPoiLayer,
  clearTrajectoryLayer: map.clearTrajectoryLayer,
  flyToPoint: map.flyToPoint,
  flyToPoints: map.flyToPoints,
  flyToCandidateAreas: map.flyToCandidateAreas,
  resizeMap: map.resizeMap,
  selectCandidateArea: map.selectCandidateArea,
  setAreaFlows: map.setAreaFlows,
  setCandidateAreas: map.setCandidateAreas,
  setDensityLayer: map.setDensityLayer,
})
</script>

<template>
  <div ref="mapElement" class="map-container"></div>
</template>

<style scoped>
.map-container {
  width: 100%;
  height: 100%;
  min-height: 340px;
  overflow: hidden;
  border-radius: 15px;
  background: #d8e5f5;
}
</style>
