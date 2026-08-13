<script setup lang="ts">
import { nextTick, onMounted, ref } from "vue"
import { fetchPoiCategories, fetchPois } from "@/api/poi"
import MapContainer from "@/components/map/MapContainer.vue"
import type { Poi } from "@/types"

const RENDER_LIMIT = 800

const mapRef = ref<InstanceType<typeof MapContainer>>()
const categories = ref<string[]>([])
const selectedCategory = ref("")
const pois = ref<Poi[]>([])
const loading = ref(false)

/**
 * 加载 POI 并刷新地图图层。
 * input: selectedCategory 当前筛选类别。
 * output: pois 状态和 Mapbox POI 图层。
 * 默认限制渲染数量，避免全量 Entity 创建阻塞主线程。
 */
const loadPois = async () => {
  loading.value = true
  try {
    pois.value = await fetchPois({ category: selectedCategory.value || undefined, limit: RENDER_LIMIT })
    await nextTick()
    mapRef.value?.addPoiLayer(pois.value)
    if (pois.value.length) {
      mapRef.value?.flyToPoint(pois.value[0].longitude, pois.value[0].latitude)
    }
  } catch {
    // 错误提示已由 request 拦截器统一处理，此处只负责恢复加载状态
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  categories.value = await fetchPoiCategories()
  await loadPois()
})
</script>

<template>
  <section v-loading="loading" class="map-page">
    <div class="page-toolbar">
      <div>
        <h2>POI 地图</h2>
        <p>当前渲染 {{ pois.length }} 个点位，默认限制 {{ RENDER_LIMIT }} 个以保持地图流畅。</p>
      </div>
      <el-select v-model="selectedCategory" clearable placeholder="全部类别" @change="loadPois">
        <el-option v-for="category in categories" :key="category" :label="category" :value="category" />
      </el-select>
    </div>

    <el-card shadow="never" class="map-card">
      <MapContainer ref="mapRef" />
    </el-card>
  </section>
</template>

<style scoped>
.map-page {
  display: grid;
  height: 100%;
  min-height: 0;
  grid-template-rows: auto minmax(0, 1fr);
}

.map-card {
  height: 100%;
  min-height: 0;
}

.page-toolbar {
  display: flex;
  min-height: 48px;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-2);
}

h2 {
  margin: 0;
  font-size: 20px;
}

.page-toolbar p {
  margin: var(--space-1) 0 0;
  color: var(--color-text-secondary);
  font-size: 14px;
}

.map-card :deep(.el-card__body) {
  height: 100%;
  padding: var(--space-2);
}
</style>
