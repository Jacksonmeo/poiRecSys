import { createRouter, createWebHistory } from "vue-router"

/**
 * Vue Router 路由配置。
 * input: 浏览器 URL。
 * output: 懒加载对应页面组件，减少首屏加载体积。
 * Dashboard 已迁移到 views/dashboard 目录，页面与子组件按业务域组织。
 */
const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", redirect: "/dashboard" },
    { path: "/dashboard", component: () => import("@/views/dashboard/Dashboard.vue") },
    { path: "/poi-map", component: () => import("@/views/PoiMap.vue") },
    { path: "/trajectory", component: () => import("@/views/TrajectoryView.vue") },
    { path: "/recommendation", component: () => import("@/views/RecommendationView.vue") },
    { path: "/model-analysis", component: () => import("@/views/ModelAnalysis.vue") },
  ],
})

export default router
