<script setup lang="ts">
import type { AnalysisMetadata } from "@/types/siteSelection"

defineProps<{ metadata: AnalysisMetadata; areaCount: number; metricCount: number }>()
</script>

<template>
  <section class="metadata-card" aria-label="分析元数据">
    <div><small>数据集</small><strong>{{ metadata.dataset }}</strong></div>
    <div><small>观测周期</small><strong>{{ metadata.observation_period || "未提供" }}</strong></div>
    <div><small>覆盖范围</small><strong>{{ areaCount }} 区域 · {{ metricCount }} 指标</strong></div>
    <div><small>配置版本</small><strong>{{ metadata.config_version }}</strong></div>
  </section>
</template>

<style scoped>
.metadata-card { display: grid; grid-template-columns: repeat(4,minmax(0,1fr)); gap: 8px; }
.metadata-card div { min-width: 0; padding: 9px 11px; border: 1px solid #e2e9f3; border-radius: 10px; background: #f9fbfe; }
small { display: block; margin-bottom: 3px; color: #8290a6; font-size: 11px; letter-spacing: .08em; }
strong { display: block; overflow: hidden; color: #26344c; font-size: 13px; font-weight: 650; text-overflow: ellipsis; white-space: nowrap; }
@media (max-width: 760px) { .metadata-card { grid-template-columns: repeat(2,minmax(0,1fr)); } }
</style>
