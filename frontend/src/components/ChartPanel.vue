<script setup lang="ts">
/**
 * ECharts 通用图表容器组件。
 *
 * 职责：
 * - 接收 EChartsOption 属性并初始化/更新图表实例
 * - 窗口 resize 时自动重绘图表
 * - 组件卸载时释放图表资源防止内存泄漏
 *
 * 使用方式：父组件传入 option，数据变化时自动刷新。
 */
import * as echarts from "echarts"
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue"

const props = defineProps<{
  /** ECharts 配置项，由父组件计算并传入 */
  option: echarts.EChartsOption
}>()

/** 图表 DOM 容器引用 */
const chartElement = ref<HTMLDivElement>()
/** ECharts 实例，延迟初始化 */
let chart: echarts.ECharts | undefined

/**
 * 渲染/更新图表。
 *
 * 首次调用时初始化 ECharts 实例（懒初始化），
 * 后续调用时更新配置项。
 * DOM 尚未挂载时跳过，避免初始化失败。
 */
const renderChart = () => {
  if (!chartElement.value) return
  // 首次渲染时初始化实例，后续复用。
  chart ??= echarts.init(chartElement.value)
  // notMerge: true 表示不合并上一份配置，完全替换。
  chart.setOption(props.option, true)
}

/**
 * 窗口大小变化时触发图表重绘。
 * 保证图表始终适应容器尺寸。
 */
const resizeChart = () => chart?.resize()

/**
 * 组件挂载：初始化图表并监听窗口 resize 事件。
 * nextTick 确保 DOM 渲染完成后再初始化，保证容器有正确的尺寸。
 */
onMounted(async () => {
  await nextTick()
  renderChart()
  window.addEventListener("resize", resizeChart)
})

/**
 * 深度监听 option 属性变化，自动刷新图表。
 * 后端数据返回后 option 更新，触发图表重绘。
 */
watch(() => props.option, renderChart, { deep: true })

/**
 * 组件卸载：移除窗口监听，销毁图表实例释放内存。
 */
onBeforeUnmount(() => {
  window.removeEventListener("resize", resizeChart)
  chart?.dispose()
})
</script>

<template>
  <!-- 图表容器由父页面控制宽度，本组件固定基础高度。 -->
  <div ref="chartElement" class="chart-panel"></div>
</template>

<style scoped>
/* ECharts 需要明确高度，否则画布会渲染为空。 */
.chart-panel {
  width: 100%;
  height: 320px;
}
</style>
