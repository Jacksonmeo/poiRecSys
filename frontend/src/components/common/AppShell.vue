<script setup lang="ts">
import {
  ChatDotRound,
  DataAnalysis,
  Location,
  MapLocation,
} from "@element-plus/icons-vue"
import { computed } from "vue"
import { useRoute } from "vue-router"
import WorkspaceStatusControls from "./WorkspaceStatusControls.vue"

const route = useRoute()

const activeTitle = computed(() => String(route.meta.title ?? "GeoAgent"))
const activeDescription = computed(() => String(route.meta.description ?? "Agentic GIS 空间决策平台"))
</script>

<template>
  <el-container class="app-shell">
    <el-aside width="216px" class="app-shell__sidebar">
      <div class="app-shell__brand">
        <span class="app-shell__logo" aria-hidden="true"><span class="app-shell__logo-dot"></span></span>
        <div class="app-shell__brand-copy">
          <strong>GeoAgent</strong>
          <span class="app-shell__brand-sub">Agentic GIS · 空间智能</span>
        </div>
      </div>

      <el-menu :default-active="route.path" router class="app-shell__menu">
        <el-menu-item index="/workspace">
          <el-icon>
            <ChatDotRound />
          </el-icon>
          <span>工作台</span>
        </el-menu-item>
        <el-sub-menu index="explore">
          <template #title><el-icon>
              <MapLocation />
            </el-icon><span>探索</span></template>
          <el-menu-item index="/explore/poi"><el-icon>
              <Location />
            </el-icon><span>POI 探索</span></el-menu-item>
          <el-menu-item index="/explore/mobility"><el-icon>
              <MapLocation />
            </el-icon><span>移动轨迹</span></el-menu-item>
          <el-menu-item index="/spatial"><el-icon>
              <DataAnalysis />
            </el-icon><span>空间分析</span></el-menu-item>
        </el-sub-menu>
      </el-menu>

    </el-aside>

    <el-container class="app-shell__body">
      <el-header class="app-shell__header">
        <div class="app-shell__heading">
          <h1>{{ activeTitle }}</h1>
          <p>{{ activeDescription }}</p>
        </div>
        <div class="app-shell__actions">
          <WorkspaceStatusControls />
          <span class="online-badge"><span class="online-badge__dot"></span>在线</span>
        </div>
      </el-header>

      <el-main class="app-shell__main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<style src="../../styles/app-shell.css" scoped></style>
