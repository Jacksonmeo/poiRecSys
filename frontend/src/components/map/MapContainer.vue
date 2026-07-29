<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue"
import "mapbox-gl/dist/mapbox-gl.css"
import { useMap } from "@/composables/useMap"
import type { MapPoint, TrajectoryLayerOptions } from "@/types/map"

const mapElement = ref<HTMLDivElement>()
const map = useMap(mapElement)

/**
 * Mapbox 地图容器组件。
 * input: 父组件通过 expose 调用图层方法并传入点位数据。
 * output: 稳定的二维地图 DOM 与轻量 Mapbox GL 实例。
 * 页面不直接操作地图 SDK，方便后续继续拆 PoiLayer/TrajectoryLayer。
 */
onMounted(map.initMap)
onBeforeUnmount(map.destroyMap)

defineExpose<{
  addPoiLayer: (points: MapPoint[]) => void
  addTrajectoryLayer: (points: MapPoint[], options?: TrajectoryLayerOptions) => void
  clearMap: () => void
  clearPoiLayer: () => void
  clearTrajectoryLayer: () => void
  flyToPoint: (lng: number, lat: number) => void
  flyToPoints: (points: MapPoint[]) => void
}>({
  addPoiLayer: map.addPoiLayer,
  addTrajectoryLayer: map.addTrajectoryLayer,
  clearMap: map.clearMap,
  clearPoiLayer: map.clearPoiLayer,
  clearTrajectoryLayer: map.clearTrajectoryLayer,
  flyToPoint: map.flyToPoint,
  flyToPoints: map.flyToPoints,
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
  border-radius: var(--radius-md);
  background: #d8e5f5;
}
</style>
