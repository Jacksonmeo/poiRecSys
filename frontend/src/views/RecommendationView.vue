<script setup lang="ts">
/**
 * 推荐结果页面。
 *
 * 页面按页读取已经离线生成的推荐 session。选中一条记录后，再请求该
 * session 的历史轨迹、真实目标和 Top-K 候选，并同步绘制到 Mapbox 地图。
 */
import { nextTick, onMounted, ref, watch } from "vue"
import { ElMessage } from "element-plus"
import { fetchRecommendationDetail, fetchRecommendations } from "@/api/recommend"
import MapContainer from "@/components/map/MapContainer.vue"
import type { RecommendationDetail, RecommendationSummary } from "@/types"
import { getPoiDisplayName } from "@/utils/poi"

// ---- 地图引用 ----
const mapRef = ref<InstanceType<typeof MapContainer>>()

// ---- 数据状态 ----
/** 当前页的推荐摘要列表 */
const recommendations = ref<RecommendationSummary[]>([])
/** 当前选中的推荐记录 key（格式："userId/sessionId"） */
const selectedKey = ref("")
/** 选中推荐的详细数据（历史轨迹 + 目标 POI + 候选列表） */
const detail = ref<RecommendationDetail>()
/** 详情加载状态 */
const loading = ref(false)
/** 列表加载状态 */
const listLoading = ref(false)

// ---- 分页状态 ----
/** 符合条件的推荐记录总数 */
const total = ref(0)
/** 当前页码（1-based） */
const currentPage = ref(1)
/** 每页条数 */
const pageSize = ref(50)
/** 用户 ID 筛选关键词 */
const userFilter = ref("")

/**
 * 加载推荐结果列表（分页 + 用户筛选）。
 *
 * 每次翻页或筛选条件变化时调用此函数。
 * 只加载当前页摘要，避免全量结果阻塞浏览器。
 * 同时更新总记录数用于分页组件。
 */
const loadRecommendations = async () => {
  listLoading.value = true
  try {
    const result = await fetchRecommendations(
      (currentPage.value - 1) * pageSize.value,
      pageSize.value,
      userFilter.value.trim() || undefined,
    )
    recommendations.value = result.items
    total.value = result.total
    // 自动选中第一条记录，触发详情加载。
    selectedKey.value = result.items[0]
      ? `${result.items[0].user_id}/${result.items[0].session_id}`
      : ""
    if (!result.items.length) {
      detail.value = undefined
      mapRef.value?.clearMap()
    }
  } catch {
    ElMessage.error("推荐结果列表加载失败，请确认后端和数据库已启动。")
  } finally {
    listLoading.value = false
  }
}

/**
 * 加载选中推荐的详细数据并渲染到地图。
 *
 * 渲染逻辑：
 * 1. 历史轨迹 → 蓝色轨迹线和圆点（不含作为评估目标的最后一个签到）
 * 2. Top-K 候选 POI → 带排名标签的彩色圆点
 * 3. 真实目标 POI → 特殊标注的绿色圆点
 * 4. 相机飞到真实目标位置
 */
const loadDetail = async () => {
  // 根据当前 selectedKey 找到对应的摘要记录。
  const current = recommendations.value.find(
    (item) => `${item.user_id}/${item.session_id}` === selectedKey.value,
  )
  if (!current) return

  loading.value = true
  try {
    detail.value = await fetchRecommendationDetail(current.user_id, current.session_id)
    await nextTick()

    // 先清空地图，再依次添加轨迹线和 POI 图层。
    mapRef.value?.clearMap()
    // 历史轨迹：映射为 MapPoint 兼容格式（补充 name 字段）。
    mapRef.value?.addTrajectoryLayer(
      detail.value.history.map((item) => ({ ...item, name: item.poi_name })),
    )
    // POI 图层：候选 POI + 真实目标（后者用特殊名称和类别标注）。
    mapRef.value?.addPoiLayer([
      ...detail.value.candidates,
      {
        ...detail.value.target_poi,
        name: `真实目标: ${getPoiDisplayName(detail.value.target_poi)}`,
        category: "真实目标",
      },
    ])
    // 将相机飞到真实目标位置。
    mapRef.value?.flyToPoint(detail.value.target_poi.lng, detail.value.target_poi.lat)
  } catch {
    ElMessage.error("推荐详情加载失败。")
  } finally {
    loading.value = false
  }
}

/**
 * 应用用户 ID 筛选条件。
 * 重置到第一页并重新加载列表。
 */
const applyUserFilter = () => {
  currentPage.value = 1
  loadRecommendations()
}

/**
 * 页码变更回调。
 * 更新当前页码并重新加载对应页的数据。
 */
const changePage = (page: number) => {
  currentPage.value = page
  loadRecommendations()
}

// 监听选中记录变化 → 自动加载详情。
watch(selectedKey, loadDetail)

// 页面挂载后加载第一页推荐列表。
onMounted(loadRecommendations)
</script>

<template>
  <section v-loading="loading" class="page">
    <div class="page-toolbar">
      <h2>推荐结果</h2>
      <div class="filters">
        <el-input v-model="userFilter" clearable placeholder="按用户 ID 筛选" @keyup.enter="applyUserFilter"
          @clear="applyUserFilter" />
        <el-button type="primary" @click="applyUserFilter">查询</el-button>
        <el-select v-model="selectedKey" v-loading="listLoading" filterable placeholder="选择推荐 session">
          <el-option v-for="item in recommendations" :key="`${item.user_id}/${item.session_id}`"
            :label="`${item.user_id} / ${item.session_id}（Top-${item.top_k}）`"
            :value="`${item.user_id}/${item.session_id}`" />
        </el-select>
      </div>
    </div>

    <el-row :gutter="16" class="content-row">
      <el-col :xs="24" :lg="17" class="map-column">
        <el-card shadow="never" class="map-card">
          <MapContainer ref="mapRef" />
        </el-card>
      </el-col>
      <el-col :xs="24" :lg="7" class="result-column">
        <el-card shadow="never" class="result-card">
          <template #header>
            <div class="card-header">
              <span>Top-K 候选</span>
              <span v-if="detail" class="session-id">{{ detail.session_id }}</span>
            </div>
          </template>
          <el-empty v-if="!detail" description="暂无推荐结果" />
          <template v-else>
            <el-table :data="detail.candidates" size="small" stripe>
              <el-table-column prop="rank" label="排名" width="60" />
              <el-table-column label="POI" min-width="130">
                <template #default="{ row }">{{ getPoiDisplayName(row) }}</template>
              </el-table-column>
              <el-table-column label="分数" width="76">
                <template #default="{ row }">{{ row.score.toFixed(3) }}</template>
              </el-table-column>
            </el-table>
            <p class="target">真实目标：{{ getPoiDisplayName(detail.target_poi) }}</p>
          </template>
        </el-card>
      </el-col>
    </el-row>

    <div class="pagination">
      <el-pagination background layout="total, prev, pager, next" :current-page="currentPage" :page-size="pageSize"
        :total="total" @current-change="changePage" />
    </div>
  </section>
</template>

<style scoped>
/* 页面由工具栏、地图/结果主体和分页栏三部分组成。 */
.page {
  display: grid;
  height: 100%;
  min-height: 0;
  grid-template-rows: auto minmax(0, 1fr) auto;
  gap: var(--space-3);
}

.page-toolbar {
  display: flex;
  align-items: center;
  gap: 20px;
  height: 48px;
}

h2 {
  flex: none;
  margin: 0;
  font-size: 20px;
}

.filters {
  display: flex;
  flex: 1;
  justify-content: flex-end;
  gap: 8px;
}

.filters .el-input {
  width: 190px;
}

.filters .el-select {
  width: min(440px, 45vw);
}

.content-row,
.map-column,
.map-card,
.result-column,
.result-card {
  height: 100%;
  min-height: 0;
}

.map-card :deep(.el-card__body) {
  height: 100%;
  padding: var(--space-2);
}

.result-card {
  height: 100%;
  overflow: auto;
}

.card-header {
  display: flex;
  justify-content: space-between;
  gap: 8px;
}

.session-id {
  overflow: hidden;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.target {
  margin-bottom: 0;
  color: var(--el-color-success);
}

.pagination {
  display: flex;
  justify-content: center;
  min-height: 36px;
}

@media (max-width: 991px) {
  .page {
    height: auto;
  }

  .page-toolbar {
    align-items: stretch;
    flex-direction: column;
    height: auto;
  }

  .filters {
    flex-wrap: wrap;
    justify-content: flex-start;
  }

  .filters .el-select {
    width: 100%;
  }

  .content-row,
  .map-column,
  .map-card,
  .result-column,
  .result-card {
    height: auto;
  }

  .map-card {
    height: 480px;
    margin-bottom: 16px;
  }
}
</style>
