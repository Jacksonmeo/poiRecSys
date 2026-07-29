<script setup lang="ts">
defineProps<{
  modelName?: string
}>()
</script>

<template>
  <header class="dashboard-header glass-panel">
    <div>
      <p class="dashboard-header__eyebrow">AI + GIS + Recommendation</p>
      <h2>Next POI 推荐与时空分析概览</h2>
      <p>聚合模型评估、行为趋势与推荐链路状态，为后续推荐解释和实验管理预留扩展入口。</p>
    </div>
    <div class="dashboard-header__badge">
      <span>Active Model</span>
      <strong>{{ modelName || "-" }}</strong>
    </div>
  </header>
</template>

<style scoped>
.dashboard-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-6);
  padding: var(--space-6);
}

.dashboard-header__eyebrow {
  margin: 0 0 var(--space-2);
  color: var(--color-primary);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0;
  text-transform: uppercase;
}

.dashboard-header h2 {
  margin: 0;
  font-size: 28px;
  line-height: 1.2;
}

.dashboard-header p {
  max-width: 680px;
  margin: var(--space-3) 0 0;
  color: var(--color-text-secondary);
  line-height: 1.7;
}

.dashboard-header__badge {
  min-width: 156px;
  padding: var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: rgba(255, 255, 255, 0.64);
}

.dashboard-header__badge span,
.dashboard-header__badge strong {
  display: block;
}

.dashboard-header__badge span {
  color: var(--color-text-secondary);
  font-size: 12px;
}

.dashboard-header__badge strong {
  margin-top: var(--space-2);
  font-size: 18px;
}
</style>
