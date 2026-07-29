<script setup lang="ts">
const steps = [
  { index: "01", title: "Trajectory Encoding", description: "抽取用户时序访问偏好与空间转移特征" },
  { index: "02", title: "Geo Context", description: "融合距离、类别与候选 POI 局部上下文" },
  { index: "03", title: "Rank & Explain", description: "输出 Top-K 推荐并支持后续解释分析" },
]
</script>

<template>
  <section class="pipeline glass-panel">
    <div>
      <h3 class="section-title">推荐链路</h3>
      <p class="section-subtitle">从签到序列到 Top-K 候选生成的核心阶段</p>
    </div>

    <div class="pipeline__steps">
      <div v-for="step in steps" :key="step.title" class="pipeline__step">
        <span class="pipeline__index">{{ step.index }}</span>
        <div>
          <strong>{{ step.title }}</strong>
          <p>{{ step.description }}</p>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.pipeline {
  padding: var(--space-5);
}

.pipeline__steps {
  display: grid;
  gap: var(--space-3);
  margin-top: var(--space-5);
}

.pipeline__step {
  display: grid;
  grid-template-columns: 42px 1fr;
  gap: var(--space-3);
  padding: var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: rgba(255, 255, 255, 0.58);
}

.pipeline__index {
  color: var(--color-primary);
  font-size: 12px;
  font-weight: 800;
}

.pipeline__step strong {
  display: block;
  font-size: 14px;
}

.pipeline__step p {
  margin: var(--space-1) 0 0;
  color: var(--color-text-secondary);
  font-size: 13px;
  line-height: 1.5;
}
</style>
