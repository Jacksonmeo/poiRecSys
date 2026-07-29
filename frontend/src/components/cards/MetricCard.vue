<script setup lang="ts">
import { computed } from "vue"
import type { DashboardMetricItem } from "@/types/model"

const props = defineProps<{
  metric: DashboardMetricItem
}>()

const toneClass = computed(() => `metric-card--${props.metric.tone}`)
</script>

<template>
  <article class="metric-card glass-panel" :class="toneClass">
    <div class="metric-card__header">
      <span class="metric-card__label">{{ metric.label }}</span>
      <span class="metric-card__dot"></span>
    </div>
    <div class="metric-card__value">
      {{ metric.value }}<small v-if="metric.suffix">{{ metric.suffix }}</small>
    </div>
    <div class="metric-card__trend">{{ metric.trend }}</div>
  </article>
</template>

<style scoped>
.metric-card {
  position: relative;
  min-height: 132px;
  padding: var(--space-5);
  overflow: hidden;
  transition:
    transform 0.18s ease,
    box-shadow 0.18s ease,
    border-color 0.18s ease;
}

.metric-card:hover {
  border-color: var(--color-border-strong);
  box-shadow: var(--shadow-hover);
  transform: translateY(-2px);
}

.metric-card::after {
  position: absolute;
  right: -36px;
  bottom: -42px;
  width: 116px;
  height: 116px;
  border-radius: 999px;
  background: var(--metric-accent);
  content: "";
  opacity: 0.12;
}

.metric-card__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.metric-card__label,
.metric-card__trend {
  color: var(--color-text-secondary);
  font-size: 13px;
}

.metric-card__dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: var(--metric-accent);
}

.metric-card__value {
  margin-top: var(--space-4);
  color: var(--color-text-primary);
  font-size: 30px;
  font-weight: 700;
  line-height: 1.1;
}

.metric-card__value small {
  margin-left: var(--space-1);
  color: var(--color-text-secondary);
  font-size: 14px;
  font-weight: 500;
}

.metric-card__trend {
  margin-top: var(--space-3);
}

.metric-card--primary {
  --metric-accent: var(--color-primary);
}

.metric-card--success {
  --metric-accent: var(--color-success);
}

.metric-card--warning {
  --metric-accent: var(--color-warning);
}

.metric-card--violet {
  --metric-accent: var(--color-violet);
}
</style>
