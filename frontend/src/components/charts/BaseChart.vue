<script setup lang="ts">
import * as echarts from "echarts"
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue"

const props = withDefaults(
  defineProps<{
    option: echarts.EChartsOption
    height?: number
  }>(),
  {
    height: 320,
  },
)

const chartElement = ref<HTMLDivElement>()
let chart: echarts.ECharts | undefined
let resizeObserver: ResizeObserver | undefined

/**
 * ECharts 通用渲染基座。
 * input: option 为业务图表生成的配置，height 控制容器高度。
 * output: 挂载并维护一个 ECharts 实例。
 * 初始化、resize、销毁统一放在这里，业务图只负责 option。
 */
const renderChart = () => {
  if (!chartElement.value) return
  chart ??= echarts.init(chartElement.value)
  chart.setOption(props.option, true)
}

const resizeChart = () => chart?.resize()

onMounted(async () => {
  await nextTick()
  renderChart()
  resizeObserver = new ResizeObserver(resizeChart)
  if (chartElement.value) resizeObserver.observe(chartElement.value)
  window.addEventListener("resize", resizeChart)
})

watch(() => props.option, renderChart, { deep: true })

onBeforeUnmount(() => {
  window.removeEventListener("resize", resizeChart)
  resizeObserver?.disconnect()
  chart?.dispose()
})
</script>

<template>
  <div ref="chartElement" class="base-chart" :style="{ height: `${height}px` }"></div>
</template>

<style scoped>
.base-chart {
  width: 100%;
  min-height: 240px;
}
</style>
