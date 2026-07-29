<script setup lang="ts">
import { Refresh } from "@element-plus/icons-vue"
import ModelPerformanceChart from "@/components/charts/ModelPerformanceChart.vue"
import MetricCard from "@/components/cards/MetricCard.vue"
import { useDashboardMetrics } from "@/composables/useDashboardMetrics"
import DashboardHeader from "./DashboardHeader.vue"
import RecommendationPipeline from "./RecommendationPipeline.vue"
import UserBehaviorChart from "./UserBehaviorChart.vue"

const { bestModel, loading, metricCards, metrics, reload } = useDashboardMetrics()
</script>

<template>
  <section class="dashboard-page">
    <DashboardHeader :model-name="bestModel?.model" />

    <el-skeleton v-if="loading && metrics.length === 0" :rows="8" animated class="dashboard-page__skeleton" />

    <template v-else>
      <div class="dashboard-page__metrics">
        <MetricCard v-for="metric in metricCards" :key="metric.label" :metric="metric" />
      </div>

      <div class="dashboard-page__grid">
        <section class="dashboard-page__chart glass-panel">
          <div class="dashboard-page__section-head">
            <div>
              <h3 class="section-title">模型指标对比</h3>
              <p class="section-subtitle">HR@5、NDCG@5、MRR@10 横向比较</p>
            </div>
            <el-button :icon="Refresh" circle :loading="loading" @click="reload" />
          </div>
          <el-empty v-if="metrics.length === 0" description="暂无模型指标数据" />
          <ModelPerformanceChart v-else :metrics="metrics" />
        </section>

        <RecommendationPipeline />
        <UserBehaviorChart />
      </div>
    </template>
  </section>
</template>

<style scoped>
.dashboard-page {
  display: grid;
  gap: var(--space-5);
}

.dashboard-page__skeleton {
  padding: var(--space-6);
}

.dashboard-page__metrics {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--space-4);
}

.dashboard-page__grid {
  display: grid;
  grid-template-columns: minmax(0, 1.5fr) minmax(320px, 0.7fr);
  gap: var(--space-4);
}

.dashboard-page__chart {
  min-width: 0;
  padding: var(--space-5);
}

.dashboard-page__section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  margin-bottom: var(--space-4);
}

.dashboard-page__grid > :last-child {
  grid-column: 2;
}
</style>
