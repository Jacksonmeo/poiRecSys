import { createRouter, createWebHistory } from "vue-router"

/**
 * 应用路由：Agentic GIS 产品页面。
 * 核心为自然语言驱动的空间决策工作台，配套三个地图探索页面。
 */
const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", redirect: "/workspace" },
    {
      path: "/workspace",
      component: () => import("@/views/workspace/SpatialWorkspace.vue"),
      meta: { title: "空间决策工作台", description: "自然语言驱动的空间分析与决策证据工作台" },
    },
    { path: "/explore", redirect: "/explore/poi" },
    {
      path: "/explore/poi",
      component: () => import("@/views/PoiMap.vue"),
      meta: { title: "POI 探索", description: "探索兴趣点分布、类别与空间聚集特征" },
    },
    {
      path: "/explore/mobility",
      component: () => import("@/views/TrajectoryView.vue"),
      meta: { title: "移动轨迹探索", description: "分析签到序列与城市移动模式" },
    },
    {
      path: "/spatial",
      component: () => import("@/views/spatial/SpatialAnalysisView.vue"),
      meta: { title: "空间分析", description: "格网密度与空间分布分析" },
    },
    { path: "/agent", redirect: "/workspace" },
    { path: "/poi-map", redirect: "/explore/poi" },
    { path: "/trajectory", redirect: "/explore/mobility" },
  ],
})

export default router
