<script setup lang="ts">
import type { AnalysisMetadata } from "@/types/siteSelection"
defineProps<{ metadata: AnalysisMetadata }>()
</script>

<template>
  <aside class="disclaimer-card">
    <strong>证据边界</strong>
    <span>仅展示 {{ metadata.dataset }} 的历史事实指标，不生成综合评分、收益预测或经营承诺。</span>
  </aside>
</template>

<style scoped>
.disclaimer-card { display: flex; min-width: 0; align-items: flex-start; gap: 8px; padding: 8px 10px; border: 1px solid #f1dfbd; border-radius: 9px; color: #7a6235; background: #fffaf0; font-size: 9px; line-height: 1.45; }
.disclaimer-card strong { flex: none; color: #a06d17; font-size: 9px; letter-spacing: .04em; }
.disclaimer-card span { min-width: 0; overflow-wrap: anywhere; }
</style>
