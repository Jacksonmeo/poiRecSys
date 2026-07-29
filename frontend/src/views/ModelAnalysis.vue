<script setup lang="ts">
/**
 * 模型分析页面。
 *
 * 功能：
 * - 上方并排展示两张 ECharts 柱状图：模型性能对比 + 消融实验
 * - 下方表格展示各模型的原始指标明细
 *
 * 数据来源：
 * - modelMetrics：fetchModelMetrics() 获取主流模型对比数据
 * - ablationMetrics：fetchAblationMetrics() 获取消融实验数据（逐步移除组件观察性能变化）
 */
import type { EChartsOption } from "echarts"
import { computed, onMounted, ref } from "vue"
import { fetchAblationMetrics, fetchModelMetrics } from "@/api/metrics"
import ChartPanel from "@/components/ChartPanel.vue"
import type { ModelMetric } from "@/types"

/** 模型性能对比指标 */
const modelMetrics = ref<ModelMetric[]>([])
/** 消融实验指标 */
const ablationMetrics = ref<ModelMetric[]>([])

/**
 * 创建通用 ECharts 柱状图配置。
 *
 * 两个图表（模型对比 / 消融实验）共用同一套生成逻辑，
 * 仅数据源和标题不同。
 *
 * @param metrics 模型指标数组
 * @param title   图表标题
 * @returns ECharts 配置对象
 */
const createOption = (metrics: ModelMetric[], title: string): EChartsOption => ({
  title: { text: title, left: "center", textStyle: { fontSize: 15, fontWeight: 400 } },
  tooltip: { trigger: "axis" },
  legend: { data: ["HR@5", "NDCG@5", "MRR@10"], bottom: 0 },
  grid: { left: 44, right: 20, top: 55, bottom: 50 },
  xAxis: { type: "category", data: metrics.map((item) => item.model) },
  yAxis: { type: "value", max: 60, name: "Score (%)" },
  series: [
    { name: "HR@5", type: "bar", data: metrics.map((item) => item.hr5) },
    { name: "NDCG@5", type: "bar", data: metrics.map((item) => item.ndcg5) },
    { name: "MRR@10", type: "bar", data: metrics.map((item) => item.mrr10) },
  ],
})

/** 模型性能对比图配置（响应式） */
const modelOption = computed(() => createOption(modelMetrics.value, "模型性能对比"))
/** 消融实验图配置（响应式） */
const ablationOption = computed(() => createOption(ablationMetrics.value, "消融实验"))

/**
 * 页面挂载后并发加载两组指标数据。
 * Promise.all 并发请求减少总等待时间。
 */
onMounted(async () => {
  ;[modelMetrics.value, ablationMetrics.value] = await Promise.all([fetchModelMetrics(), fetchAblationMetrics()])
})
</script>

<template>
  <!-- 上方两张图表，下方表格展示原始指标明细。 -->
  <section>
    <h2>模型指标分析</h2>
    <el-row :gutter="16">
      <el-col :xs="24" :xl="12">
        <el-card shadow="never"><ChartPanel :option="modelOption" /></el-card>
      </el-col>
      <el-col :xs="24" :xl="12">
        <el-card shadow="never"><ChartPanel :option="ablationOption" /></el-card>
      </el-col>
    </el-row>
    <el-card shadow="never" class="table-card">
      <template #header>模型指标明细</template>
      <el-table :data="modelMetrics" stripe>
        <el-table-column prop="model" label="模型" />
        <el-table-column prop="hr5" label="HR@5 (%)" />
        <el-table-column prop="ndcg5" label="NDCG@5 (%)" />
        <el-table-column prop="mrr10" label="MRR@10 (%)" />
      </el-table>
    </el-card>
  </section>
</template>

<style scoped>
/* 页面标题保持与其他视图一致。 */
h2 {
  margin-top: 0;
  font-size: 20px;
}

/* 表格与图表之间保留间距。 */
.table-card {
  margin-top: 16px;
}
</style>
