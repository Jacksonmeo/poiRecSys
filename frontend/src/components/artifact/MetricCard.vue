<script setup lang="ts">
import { computed } from "vue"
import type { AreaMetric } from "@/types/siteSelection"
import { metricLabel, metricUnit } from "@/utils/siteSelection"

const props = defineProps<{ metric: AreaMetric }>()
/** 将指标数值格式化为中文 locale，避免长小数直接占满卡片。 */
const formattedValue = computed(() => new Intl.NumberFormat("zh-CN", {
  maximumFractionDigits: 2,
}).format(props.metric.value))
</script>

<template>
  <article class="metric-card" :title="metric.description">
    <span>{{ metricLabel(metric.metric_id) }}</span>
    <div><strong>{{ formattedValue }}</strong><span class="unit">{{ metricUnit(metric) }}</span></div>
    <p>{{ metric.description }}</p>
  </article>
</template>

<style scoped>
.metric-card { min-width: 0; padding: 10px 11px; border: 1px solid #e1e8f3; border-radius: 11px; background: linear-gradient(145deg,#fff,#f8faff); }
.metric-card > span { color: #66758d; font-size: 13px; }
.metric-card div { display: flex; align-items: baseline; gap: 4px; margin-top: 3px; color: #1b2a44; }
.metric-card strong { font-family: var(--font-mono); font-size: 17px; }
.metric-card .unit { color: #8491a5; font-size: 12px; }
.metric-card p { overflow: hidden; margin: 3px 0 0; color: #96a1b1; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
</style>
