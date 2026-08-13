<script setup lang="ts">
import { computed } from "vue"
import type { AgentMapLayer } from "@/types/agent"
import type { SiteSelectionArtifact } from "@/types/siteSelection"

const props = defineProps<{
  layers: AgentMapLayer[]
  artifact?: SiteSelectionArtifact | null
  working?: boolean
}>()

/** 根据当前工作台状态选择地图左上角的分析标题。 */
const analysis = computed(() => {
  if (props.working) return "Agent 正在执行空间任务"
  if (props.artifact) return "商业选址证据分析"
  if (props.layers.some((layer) => layer.type === "trajectory")) return "用户轨迹分析"
  if (props.layers.some((layer) => layer.type === "heatmap")) return "POI 密度热力图"
  if (props.layers.some((layer) => layer.type === "poi")) return "POI 空间查询"
  return "等待空间分析任务"
})

/** 显示当前 artifact 或图层使用的数据来源。 */
const source = computed(() => props.artifact?.metadata.dataset
  ?? (props.layers.some((layer) => layer.type === "trajectory") ? "用户签到历史" : "东京数据集"))
/** 计算当前地图可视化结果的数量摘要。 */
const count = computed(() => props.artifact?.candidate_areas.length
  ?? props.layers.reduce((sum, layer) => sum + layer.data.length, 0))
</script>

<template>
  <aside class="map-status" :class="{ 'is-working': working }">
    <div class="map-status__head">
      <span class="map-status__signal"><span class="dot" /></span>
      <span><span class="meta">当前分析</span><strong>{{ analysis }}</strong></span>
      <span class="state">{{ working ? "执行中" : (layers.length || artifact) ? "已就绪" : "等待中" }}</span>
    </div>
    <dl class="map-status__meta">
      <div><dt>区域</dt><dd>东京</dd></div>
      <div><dt>数据源</dt><dd>{{ source }}</dd></div>
      <div v-if="count"><dt>结果</dt><dd>{{ count }} {{ artifact ? "个候选区域" : "条记录" }}</dd></div>
    </dl>
  </aside>
</template>

<style scoped>
.map-status { width: 286px; padding: 12px 13px; border: 1px solid rgba(207,220,234,.96); border-radius: 14px; background: rgba(255,255,255,.95); box-shadow: 0 14px 34px rgba(47,67,109,.14); backdrop-filter: blur(14px); }
.map-status__head { display: flex; align-items: center; gap: 9px; padding-bottom: 9px; border-bottom: 1px solid #edf1f6; }
.map-status__signal { display: grid; width: 30px; height: 30px; flex: none; place-items: center; border-radius: 9px; background: linear-gradient(145deg,#5b76ef,#465fda); box-shadow: 0 6px 14px rgba(70,95,218,.22); }
.map-status__signal .dot { width: 9px; height: 9px; border: 2px solid #fff; border-radius: 50%; box-shadow: 0 0 0 4px rgba(255,255,255,.16); }
.map-status.is-working .map-status__signal .dot { animation: pulse 1.2s ease-in-out infinite; }
.map-status__head > span:nth-child(2) { min-width: 0; flex: 1; }
.map-status__head .meta,.map-status__head strong { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.map-status__head .meta { color: #7285b4; font-size: 10px; letter-spacing: .08em; }
.map-status__head strong { margin-top: 3px; color: #2c3a53; font-size: 13px; }
.map-status__head .state { padding: 3px 7px; border-radius: 999px; color: #29946e; background: #e9f7f2; font-size: 10px; font-style: normal; }
.map-status.is-working .map-status__head .state { color: #3374d4; background: #ebf3ff; }
.map-status__meta { display: grid; gap: 5px; margin: 8px 0 0; padding: 0; }
.map-status__meta div { display: grid; grid-template-columns: 48px minmax(0,1fr); gap: 7px; font-size: 11px; }
.map-status__meta dt { color: #98a3b4; }
.map-status__meta dd { margin: 0; overflow: hidden; color: #5b687d; text-overflow: ellipsis; white-space: nowrap; }
@keyframes pulse { 50% { opacity: .35; transform: scale(.72); } }
</style>
