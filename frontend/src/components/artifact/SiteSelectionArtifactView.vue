<script setup lang="ts">
import { computed } from "vue"
import type { SiteSelectionArtifact } from "@/types/siteSelection"
import { enrichCandidateAreas, metricsByArea } from "@/utils/siteSelection"
import AreaComparisonTable from "./AreaComparisonTable.vue"
import DisclaimerCard from "./DisclaimerCard.vue"
import FlowPanel from "./FlowPanel.vue"
import MetadataCard from "./MetadataCard.vue"
import MetricCard from "./MetricCard.vue"

const props = defineProps<{
  artifact: SiteSelectionArtifact
  selectedArea: string | null
}>()

defineEmits<{ selectArea: [areaId: string] }>()

/** 补齐候选区域几何信息，供表格和地图共同使用。 */
const areas = computed(() => enrichCandidateAreas(props.artifact.candidate_areas))
/** 将 artifact 指标预先按区域分组。 */
const groupedMetrics = computed(() => metricsByArea(props.artifact))
/** 根据当前选择确定证据面板右侧要展示的区域。 */
const activeArea = computed(() => areas.value.find((area) => area.area_id === props.selectedArea)
  ?? areas.value[0])
/** 返回当前区域的全部指标卡片数据。 */
const activeMetrics = computed(() => activeArea.value
  ? groupedMetrics.value[activeArea.value.area_id] ?? []
  : [])
</script>

<template>
  <section class="artifact-view">
    <header class="artifact-view__header">
      <div>
        <span>结构化分析结果 · 选址分析</span>
        <h3>选址证据工作台</h3>
      </div>
      <div class="artifact-view__status"><span class="dot" />已生成</div>
    </header>

    <MetadataCard
      :metadata="artifact.metadata"
      :area-count="areas.length"
      :metric-count="artifact.metrics.length"
    />

    <div class="artifact-view__grid">
      <section class="artifact-view__comparison">
        <div class="artifact-view__section-title">
          <h4>候选区域事实对比</h4><span>点击行可与地图联动</span>
        </div>
        <AreaComparisonTable
          :areas="areas"
          :metrics="groupedMetrics"
          :selected-area="selectedArea"
          @select="$emit('selectArea', $event)"
        />
      </section>

      <aside class="artifact-view__detail">
        <div class="artifact-view__section-title">
          <h4>{{ activeArea?.display_name || "区域详情" }}</h4><span>{{ activeArea?.area_id }}</span>
        </div>
        <div class="artifact-view__metrics">
          <MetricCard v-for="metric in activeMetrics" :key="metric.metric_id" :metric="metric" />
        </div>
        <FlowPanel
          :flows="artifact.flows"
          :areas="areas"
          :selected-area="selectedArea"
          @select="$emit('selectArea', $event)"
        />
      </aside>
    </div>

    <DisclaimerCard :metadata="artifact.metadata" />
  </section>
</template>

<style scoped>
.artifact-view { display: grid; gap: 10px; padding: 12px; color: #26344c; background: #fff; }
.artifact-view__header,.artifact-view__section-title { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.artifact-view__header span { color: #7186bd; font-size: 11px; letter-spacing: .08em; }
.artifact-view__header h3 { margin: 2px 0 0; font-size: 18px; }
.artifact-view__status { display: flex; align-items: center; gap: 5px; color: #468168; font-size: 12px; }
.artifact-view__status .dot { width: 7px; height: 7px; border-radius: 50%; background: #38ae7b; box-shadow: 0 0 0 4px #e3f6ed; }
.artifact-view__grid { display: grid; grid-template-columns: minmax(0,1.45fr) minmax(240px,.8fr); gap: 12px; min-height: 0; }
.artifact-view__comparison,.artifact-view__detail { min-width: 0; }
.artifact-view__detail { display: grid; align-content: start; gap: 8px; }
.artifact-view__section-title { margin-bottom: 6px; }
.artifact-view__section-title h4 { margin: 0; font-size: 14px; }
.artifact-view__section-title span { color: #8a97a9; font-size: 11px; }
.artifact-view__metrics { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 6px; }
@media (max-width: 980px) { .artifact-view__grid { grid-template-columns: 1fr; } }
</style>
