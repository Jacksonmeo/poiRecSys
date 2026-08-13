<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue"
import MapContainer from "./MapContainer.vue"
import MapInsightCard from "./MapInsightCard.vue"
import MapLegend from "./MapLegend.vue"
import MapRecommendationCard from "./MapRecommendationCard.vue"
import MapStatusBar from "./MapStatusBar.vue"
import type { AgentMapLayer } from "@/types/agent"
import type { MapPoint } from "@/types/map"
import type { DensityCell } from "@/types/spatial"
import type { SiteSelectionArtifact } from "@/types/siteSelection"
import { enrichCandidateAreas } from "@/utils/siteSelection"

const props = defineProps<{
  layers: AgentMapLayer[]
  artifact?: SiteSelectionArtifact | null
  selectedArea?: string | null
  working?: boolean
}>()

const emit = defineEmits<{ selectArea: [areaId: string] }>()
const mapRef = ref<InstanceType<typeof MapContainer>>()
const poiPoints = computed(() => props.layers
  .filter((layer) => layer.type === "poi")
  .flatMap((layer) => layer.data as unknown as MapPoint[]))
const topRecommendation = computed(() => poiPoints.value
  .find((point) => point.rank === 1 && typeof point.score === "number"))
const hasResults = computed(() => Boolean(props.layers.length || props.artifact))

/** 将地图卡片中的点位点击事件转换为镜头移动。 */
const focusPoint = (point: MapPoint) => {
  if (Number.isFinite(point.longitude) && Number.isFinite(point.latitude)) {
    mapRef.value?.flyToPoint(point.longitude as number, point.latitude as number)
  }
}

/** 根据 Agent 返回的 map_layers 重建 POI、热力图和轨迹图层。 */
const applyLayers = () => {
  const map = mapRef.value
  if (!map) return
  map.clearDensityLayer()
  map.clearPoiLayer()
  map.clearTrajectoryLayer()
  const heatmap = props.layers.filter((layer) => layer.type === "heatmap")
    .flatMap((layer) => layer.data as unknown as DensityCell[])
  const pois = poiPoints.value
  const trajectory = props.layers.filter((layer) => layer.type === "trajectory")
    .flatMap((layer) => layer.data as unknown as MapPoint[])
  if (heatmap.length) map.setDensityLayer(heatmap)
  if (pois.length) {
    map.addPoiLayer(pois)
    map.flyToPoints(pois)
  }
  if (trajectory.length) map.addTrajectoryLayer(trajectory)
}

/** 将选址 artifact 的候选区域、迁移流和当前选择同步到地图。 */
const applyArtifact = () => {
  const map = mapRef.value
  if (!map) return
  const areas = enrichCandidateAreas(props.artifact?.candidate_areas ?? [])
  map.setCandidateAreas(areas)
  map.setAreaFlows(props.artifact?.flows ?? [], areas)
  map.selectCandidateArea(props.selectedArea ?? null)
  if (areas.length) {
    window.requestAnimationFrame(() => window.requestAnimationFrame(() => {
      map.resizeMap()
      map.flyToCandidateAreas(areas)
    }))
  }
}

onMounted(() => {
  applyLayers()
  applyArtifact()
})
watch(() => props.layers, applyLayers, { deep: true })
watch(() => props.artifact, applyArtifact, { deep: true })
watch(() => props.selectedArea, (areaId) => mapRef.value?.selectCandidateArea(areaId ?? null))
</script>

<template>
  <div class="map-renderer">
    <MapContainer ref="mapRef" @select-area="emit('selectArea', $event)" />
    <MapStatusBar class="map-renderer__status" :layers="layers" :artifact="artifact" :working="working" />

    <div v-if="working && !hasResults" class="map-renderer__working">
      <span><i /></span>
      <strong>Agent 正在构建空间证据</strong>
      <small>理解任务 · 调用工具 · 生成分析结果</small>
    </div>
    <!-- <div v-else-if="!hasResults" class="map-renderer__empty">
      <span>⌖</span>
      <strong>空间画布已就绪</strong>
      <small>候选区域与迁移关系将在这里形成可交互图层</small>
    </div> -->

    <MapInsightCard class="map-renderer__insight" :points="poiPoints" @select="focusPoint" />
    <MapRecommendationCard
      v-if="topRecommendation"
      class="map-renderer__recommendation"
      :point="topRecommendation"
      @select="focusPoint"
    />
    <MapLegend class="map-renderer__legend" :layers="layers" :has-site-selection="Boolean(artifact)" />
  </div>
</template>

<style scoped>
.map-renderer { position: relative; height: 100%; min-height: 0; }
.map-renderer__status { position: absolute; z-index: 3; top: 14px; left: 14px; }
.map-renderer__insight { position: absolute; z-index: 3; top: 42%; right: 14px; transform: translateY(-50%); }
.map-renderer__recommendation { position: absolute; z-index: 3; bottom: 78px; left: 14px; }
.map-renderer__legend { position: absolute; z-index: 3; right: 14px; bottom: 14px; }
.map-renderer__empty,.map-renderer__working { position: absolute; z-index: 2; top: 50%; left: 50%; display: grid; place-items: center; min-width: 240px; padding: 18px 22px; border: 1px solid rgba(210,223,236,.9); border-radius: 16px; background: rgba(255,255,255,.88); box-shadow: 0 12px 30px rgba(51,70,108,.1); backdrop-filter: blur(12px); transform: translate(-50%,-50%); }
.map-renderer__empty > span { display: grid; width: 38px; height: 38px; place-items: center; margin-bottom: 8px; border-radius: 12px; color: #4d6cec; background: #edf2ff; font-size: 20px; }
.map-renderer__empty strong,.map-renderer__working strong { color: #38465d; font-size: 10px; }
.map-renderer__empty small,.map-renderer__working small { margin-top: 4px; color: #929eaf; font-size: 8px; }
.map-renderer__working > span { position: relative; display: block; width: 44px; height: 44px; margin-bottom: 9px; border: 1px solid #94c9f2; border-radius: 50%; animation: rotate 2.4s linear infinite; }
.map-renderer__working > span::after { position: absolute; inset: 8px; content: ""; border: 1px dashed #7b69e9; border-radius: 50%; }
.map-renderer__working > span i { position: absolute; top: -3px; left: 19px; width: 6px; height: 6px; border-radius: 50%; background: #31c7ee; box-shadow: 0 0 9px #31c7ee; }
@keyframes rotate { to { transform: rotate(360deg); } }
@media (max-width: 1100px) { .map-renderer__recommendation { display: none; } }
@media (max-width: 760px) { .map-renderer__insight { display: none; } .map-renderer__status { right: 14px; } }
</style>
