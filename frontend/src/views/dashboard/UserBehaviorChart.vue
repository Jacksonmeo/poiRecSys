<script setup lang="ts">
import type { EChartsOption } from "echarts"
import { computed } from "vue"
import BaseChart from "@/components/charts/BaseChart.vue"

const option = computed<EChartsOption>(() => ({
  color: ["#06aed4"],
  grid: { top: 18, right: 18, bottom: 28, left: 32 },
  tooltip: { trigger: "axis" },
  xAxis: {
    type: "category",
    boundaryGap: false,
    data: ["00:00", "04:00", "08:00", "12:00", "16:00", "20:00"],
    axisTick: { show: false },
    axisLabel: { color: "#667085" },
    axisLine: { lineStyle: { color: "rgba(16, 24, 40, 0.12)" } },
  },
  yAxis: {
    type: "value",
    splitLine: { lineStyle: { color: "rgba(16, 24, 40, 0.08)" } },
    axisLabel: { color: "#667085" },
  },
  series: [
    {
      name: "活跃度",
      type: "line",
      smooth: true,
      symbolSize: 7,
      areaStyle: { opacity: 0.14 },
      data: [18, 10, 36, 52, 47, 66],
    },
  ],
}))
</script>

<template>
  <section class="behavior glass-panel">
    <h3 class="section-title">用户行为节律</h3>
    <p class="section-subtitle">用于占位展示时段活跃趋势，后续接入真实签到聚合接口</p>
    <BaseChart :option="option" :height="236" />
  </section>
</template>

<style scoped>
.behavior {
  padding: var(--space-5);
}
</style>
