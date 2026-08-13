<script setup lang="ts">
import { computed, ref } from "vue"
import { fetchDensityGrid } from "@/api/spatial"
import type { Bbox, DensityCell } from "@/types/spatial"
import SpatialFilterPanel from "./components/SpatialFilterPanel.vue"
import SpatialHeatmap from "./components/SpatialHeatmap.vue"

const loading = ref(false)
const cells = ref<DensityCell[]>([])
const lastBbox = ref<Bbox | null>(null)

/** 命中 POI 总数：格网 count 之和。 */
const totalCount = computed(() => cells.value.reduce((sum, cell) => sum + cell.count, 0))

/**
 * 按区域 + 格网数发起密度分析，结果渲染为地图热力图。
 * 错误提示由 request 拦截器统一处理，此处只清空旧数据。
 */
const analyze = async (bbox: Bbox, gridSize: number) => {
  loading.value = true
  try {
    cells.value = await fetchDensityGrid(bbox, gridSize)
    lastBbox.value = bbox
  } catch {
    cells.value = []
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <section class="spatial-page">
    <div class="page-toolbar">
      <div>
        <h2>空间密度分析</h2>
        <p>选择区域与格网精度，调用 PostGIS 密度接口生成热力数据（Stage 2 空间能力验证）。</p>
      </div>
      <div class="page-toolbar__stats">
        <span>命中 POI：<strong>{{ totalCount }}</strong></span>
        <span>格点数：<strong>{{ cells.length }}</strong></span>
      </div>
    </div>

    <el-card shadow="never" class="filter-card">
      <SpatialFilterPanel :loading="loading" @analyze="analyze" />
    </el-card>

    <el-card shadow="never" class="map-card">
      <SpatialHeatmap :cells="cells" />
    </el-card>
  </section>
</template>

<style scoped>
.spatial-page {
  display: grid;
  height: 100%;
  min-height: 0;
  grid-template-rows: auto auto minmax(0, 1fr);
  gap: var(--space-3);
}

.page-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.page-toolbar h2 {
  margin: 0;
  font-size: 20px;
}

.page-toolbar p {
  margin: var(--space-1) 0 0;
  color: var(--color-text-secondary);
  font-size: 13px;
}

.page-toolbar__stats {
  display: flex;
  gap: var(--space-4);
  color: var(--color-text-secondary);
  font-size: 13px;
}

.page-toolbar__stats strong {
  color: var(--color-primary);
}

.filter-card :deep(.el-card__body) {
  padding: var(--space-3) var(--space-4);
}

.map-card {
  height: 100%;
  min-height: 0;
}

.map-card :deep(.el-card__body) {
  height: 100%;
  padding: var(--space-2);
}
</style>
