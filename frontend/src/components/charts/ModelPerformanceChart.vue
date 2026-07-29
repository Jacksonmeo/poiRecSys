<script setup lang="ts">
import type { EChartsOption } from "echarts"
import { computed } from "vue"
import BaseChart from "@/components/charts/BaseChart.vue"
import type { ModelMetric } from "@/types/model"

const props = defineProps<{
  metrics: ModelMetric[]
}>()

/**
 * 生成模型性能对比图配置。
 * input: metrics 为多个模型的 HR@5、NDCG@5、MRR@10。
 * output: BaseChart 可直接渲染的 ECharts option。
 * 图表逻辑独立于页面，后续可复用于 Model Analysis。
 */
const option = computed<EChartsOption>(() => ({
  color: ["#246bfe", "#12b76a", "#7a5af8"],
  grid: { top: 48, right: 20, bottom: 34, left: 42 },
  legend: {
    top: 0,
    icon: "roundRect",
    itemWidth: 12,
    itemHeight: 8,
    textStyle: { color: "#667085" },
  },
  tooltip: {
    trigger: "axis",
    backgroundColor: "rgba(16, 24, 40, 0.88)",
    borderWidth: 0,
    textStyle: { color: "#fff" },
  },
  xAxis: {
    type: "category",
    data: props.metrics.map((item) => item.model),
    axisLine: { lineStyle: { color: "rgba(16, 24, 40, 0.12)" } },
    axisLabel: { color: "#667085" },
    axisTick: { show: false },
  },
  yAxis: {
    type: "value",
    name: "Score (%)",
    max: 60,
    splitLine: { lineStyle: { color: "rgba(16, 24, 40, 0.08)" } },
    axisLabel: { color: "#667085" },
    nameTextStyle: { color: "#98a2b3" },
  },
  series: [
    { name: "HR@5", type: "bar", barMaxWidth: 28, data: props.metrics.map((item) => item.hr5) },
    { name: "NDCG@5", type: "bar", barMaxWidth: 28, data: props.metrics.map((item) => item.ndcg5) },
    { name: "MRR@10", type: "bar", barMaxWidth: 28, data: props.metrics.map((item) => item.mrr10) },
  ],
}))
</script>

<template>
  <BaseChart :option="option" :height="336" />
</template>
