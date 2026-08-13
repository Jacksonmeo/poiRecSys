<script setup lang="ts">
import { ref } from "vue"
import type { Bbox } from "@/types/spatial"

defineProps<{ loading: boolean }>()
const emit = defineEmits<{ analyze: [bbox: Bbox, gridSize: number] }>()

/** 预设分析区域（东京都市圈）。 */
const PRESET_AREAS: Array<{ label: string; bbox: Bbox }> = [
  { label: "东京中心", bbox: { min_lon: 139.69, min_lat: 35.64, max_lon: 139.81, max_lat: 35.72 } },
  { label: "涩谷", bbox: { min_lon: 139.68, min_lat: 35.64, max_lon: 139.72, max_lat: 35.67 } },
  { label: "新宿", bbox: { min_lon: 139.69, min_lat: 35.68, max_lon: 139.72, max_lat: 35.71 } },
  { label: "银座", bbox: { min_lon: 139.75, min_lat: 35.66, max_lon: 139.78, max_lat: 35.68 } },
  { label: "全域（东京）", bbox: { min_lon: 139.3, min_lat: 35.4, max_lon: 140.2, max_lat: 35.9 } },
]

const selectedArea = ref(PRESET_AREAS[0])
const gridSize = ref(10)

/** 将当前区域和格网配置提交给父页面发起密度分析。 */
const analyze = () => emit("analyze", selectedArea.value.bbox, gridSize.value)
</script>

<template>
  <div class="filter-panel">
    <el-select v-model="selectedArea" class="filter-panel__area">
      <el-option v-for="area in PRESET_AREAS" :key="area.label" :label="area.label" :value="area" />
    </el-select>

    <div class="filter-panel__grid">
      <span class="filter-panel__label">格网 {{ gridSize }}×{{ gridSize }}</span>
      <el-slider v-model="gridSize" :min="2" :max="30" class="filter-panel__slider" />
    </div>

    <el-button type="primary" :loading="loading" @click="analyze">分析密度</el-button>
  </div>
</template>

<style scoped>
.filter-panel {
  display: flex;
  align-items: center;
  gap: var(--space-4);
}

.filter-panel__area {
  width: 180px;
}

.filter-panel__grid {
  display: flex;
  flex: 1;
  align-items: center;
  gap: var(--space-3);
}

.filter-panel__label {
  flex-shrink: 0;
  color: var(--color-text-secondary);
  font-size: 13px;
}

.filter-panel__slider {
  max-width: 260px;
}
</style>
