<script setup lang="ts">
import { computed } from "vue"
import type { AreaMetric, CandidateArea } from "@/types/siteSelection"
import { areaColor, metricLabel, metricUnit } from "@/utils/siteSelection"

const props = defineProps<{
  areas: CandidateArea[]
  metrics: Record<string, AreaMetric[]>
  selectedArea: string | null
}>()

defineEmits<{ select: [areaId: string] }>()

const metricIds = computed(() => Array.from(new Set(
  props.areas.flatMap((area) => (props.metrics[area.area_id] ?? []).map((metric) => metric.metric_id)),
)))

/** 从当前区域的指标列表中查找指定指标，供表格单元格渲染。 */
const findMetric = (areaId: string, metricId: string) =>
  props.metrics[areaId]?.find((metric) => metric.metric_id === metricId)
</script>

<template>
  <div class="comparison-table">
    <table>
      <thead><tr><th>候选区域</th><th v-for="id in metricIds" :key="id">{{ metricLabel(id) }}</th></tr></thead>
      <tbody>
        <tr
          v-for="area in areas"
          :key="area.area_id"
          :class="{ 'is-selected': area.area_id === selectedArea }"
          tabindex="0"
          @click="$emit('select', area.area_id)"
          @keydown.enter="$emit('select', area.area_id)"
        >
          <th><i :style="{ background: areaColor(area.area_id) }" />{{ area.display_name }}</th>
          <td v-for="id in metricIds" :key="id">
            {{ findMetric(area.area_id, id)?.value ?? "—" }}
            <small v-if="findMetric(area.area_id, id)">{{ metricUnit(findMetric(area.area_id, id)!) }}</small>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.comparison-table { overflow: auto; border: 1px solid #e0e8f3; border-radius: 11px; }
table { width: 100%; min-width: 520px; border-collapse: collapse; font-size: 10px; }
th,td { padding: 8px 10px; border-bottom: 1px solid #edf1f6; text-align: right; white-space: nowrap; }
thead th { position: sticky; top: 0; color: #75839a; background: #f6f8fc; font-size: 9px; font-weight: 650; }
th:first-child { text-align: left; }
tbody tr { cursor: pointer; transition: background .16s ease; }
tbody tr:hover { background: #f7f9ff; }
tbody tr.is-selected { background: #eef2ff; box-shadow: inset 3px 0 #4967f2; }
tbody tr:last-child th,tbody tr:last-child td { border-bottom: 0; }
tbody th { color: #2c3a52; font-weight: 650; }
i { display: inline-block; width: 7px; height: 7px; margin-right: 6px; border-radius: 50%; }
td { color: #3d4b63; font-family: var(--font-mono); }
td small { margin-left: 2px; color: #9aa5b5; font-family: inherit; }
</style>
