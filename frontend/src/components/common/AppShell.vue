<script setup lang="ts">
import { DataAnalysis, Location, MapLocation, Promotion, TrendCharts } from "@element-plus/icons-vue"
import { computed } from "vue"
import { useRoute } from "vue-router"

const route = useRoute()

/**
 * 应用主壳层导航配置。
 * input: 当前路由路径。
 * output: 左侧导航项与顶部上下文说明。
 * 顶部不再重复页面主标题，避免和各业务页面的 h2 形成双标题。
 */
const menuItems = [
  { path: "/dashboard", label: "数据看板", icon: DataAnalysis, description: "实验与运营指标" },
  { path: "/poi-map", label: "POI 地图", icon: Location, description: "空间分布分析" },
  { path: "/trajectory", label: "用户轨迹", icon: MapLocation, description: "签到序列洞察" },
  { path: "/recommendation", label: "推荐结果", icon: Promotion, description: "Top-K 解释" },
  { path: "/model-analysis", label: "模型分析", icon: TrendCharts, description: "实验对比" },
]

const activeMenu = computed(() => menuItems.find((item) => item.path === route.path) ?? menuItems[0])
</script>

<template>
  <el-container class="app-shell">
    <el-aside width="248px" class="app-shell__sidebar">
      <div class="app-shell__brand">
        <span class="app-shell__logo">N</span>
        <div>
          <strong>Next POI</strong>
          <small>Geo Intelligence</small>
        </div>
      </div>

      <el-menu :default-active="route.path" router class="app-shell__menu">
        <el-menu-item v-for="item in menuItems" :key="item.path" :index="item.path">
          <el-icon><component :is="item.icon" /></el-icon>
          <span>{{ item.label }}</span>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <el-container class="app-shell__body">
      <el-header class="app-shell__header">
        <div>
          <span class="app-shell__eyebrow">Next POI Platform</span>
          <p>{{ activeMenu.description }}</p>
        </div>
        <div class="app-shell__status">
          <span></span>
          Research Platform
        </div>
      </el-header>

      <el-main class="app-shell__main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.app-shell {
  height: 100vh;
  overflow: hidden;
}

.app-shell__sidebar {
  position: sticky;
  top: 0;
  height: 100vh;
  border-right: 1px solid var(--color-border);
  background: rgba(255, 255, 255, 0.72);
  backdrop-filter: blur(22px);
}

.app-shell__brand {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  height: 76px;
  padding: 0 var(--space-5);
}

.app-shell__logo {
  display: grid;
  width: 36px;
  height: 36px;
  place-items: center;
  border-radius: var(--radius-md);
  color: #fff;
  background: linear-gradient(135deg, var(--color-primary), var(--color-cyan));
  font-weight: 800;
}

.app-shell__brand strong,
.app-shell__brand small {
  display: block;
}

.app-shell__brand small {
  margin-top: var(--space-1);
  color: var(--color-text-secondary);
  font-size: 12px;
}

.app-shell__menu {
  border-right: 0;
  background: transparent;
}

.app-shell__menu :deep(.el-menu-item) {
  height: 44px;
  margin: var(--space-1) var(--space-3);
  border-radius: var(--radius-md);
  color: var(--color-text-secondary);
}

.app-shell__menu :deep(.el-menu-item.is-active) {
  color: var(--color-primary);
  background: var(--color-primary-soft);
}

.app-shell__body {
  height: 100vh;
  min-width: 0;
}

.app-shell__header {
  display: flex;
  height: 68px;
  align-items: center;
  justify-content: space-between;
  padding: 0 var(--space-8);
  border-bottom: 1px solid var(--color-border);
  background: rgba(255, 255, 255, 0.58);
  backdrop-filter: blur(16px);
}

.app-shell__eyebrow {
  color: var(--color-text-secondary);
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
}

.app-shell__header p {
  margin: var(--space-1) 0 0;
  color: var(--color-text-primary);
  font-size: 15px;
  font-weight: 650;
}

.app-shell__status {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--color-text-secondary);
  font-size: 13px;
}

.app-shell__status span {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: var(--color-success);
  box-shadow: 0 0 0 4px rgba(18, 183, 106, 0.12);
}

.app-shell__main {
  height: calc(100vh - 68px);
  min-height: 0;
  overflow: auto;
  padding: var(--space-6) var(--space-8);
}
</style>
