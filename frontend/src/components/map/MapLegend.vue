<script setup lang="ts">
import { computed } from "vue"
import type { AgentMapLayer, AgentMapLayerType } from "@/types/agent"

const props = defineProps<{ layers: AgentMapLayer[]; hasSiteSelection?: boolean }>()
const activeTypes = computed(() => new Set(props.layers.map((layer) => layer.type)))
/** 判断图例项是否对应当前可见图层；没有图层信息时默认全部可用。 */
const isActive = (type: AgentMapLayerType) => !props.layers.length || activeTypes.value.has(type)
</script>

<template>
  <div class="map-legend">
      <div class="map-legend__title"><span>图例</span></div>
    <template v-if="hasSiteSelection">
      <div class="map-legend__item"><span class="map-legend__area" /><span>候选区域（1km）</span></div>
      <div class="map-legend__item"><span class="map-legend__flow" /><span>区域迁移流</span></div>
      <div class="map-legend__item"><span class="map-legend__selected" /><span>当前选中区域</span></div>
    </template>
    <template v-else>
      <div class="map-legend__item" :class="{ 'is-muted': !isActive('poi') }"><span class="map-legend__dot" /><span>POI 点位</span></div>
      <div class="map-legend__item" :class="{ 'is-muted': !isActive('heatmap') }"><span class="map-legend__heat" /><span>热力分布（低 → 高）</span></div>
      <div class="map-legend__item" :class="{ 'is-muted': !isActive('trajectory') }"><span class="map-legend__line" /><span>历史用户轨迹</span></div>
    </template>
  </div>
</template>

<style scoped>
.map-legend { width: 198px; padding: 10px 12px 11px; border: 1px solid rgba(211,222,235,.95); border-radius: 13px; background: rgba(255,255,255,.94); box-shadow: 0 12px 30px rgba(50,69,109,.12); backdrop-filter: blur(14px); }
.map-legend__title { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; padding-bottom: 7px; border-bottom: 1px solid #edf1f5; color: #39475f; font-size: 12px; font-weight: 750; }
.map-legend__item { display: flex; min-height: 27px; align-items: center; gap: 9px; color: #68778e; font-size: 12px; transition: opacity .2s ease; }
.map-legend__item.is-muted { opacity: .34; }
.map-legend__dot { width: 8px; height: 8px; margin-left: 4px; border: 1.5px solid #fff; border-radius: 50%; background: #2f65ec; box-shadow: 0 0 0 2px #dce7ff; }
.map-legend__heat { width: 34px; height: 8px; border-radius: 999px; background: linear-gradient(90deg,#2b7df4,#32e2cf,#f6dd49,#f16748); }
.map-legend__line,.map-legend__flow { width: 34px; height: 0; border-top: 2px dashed #536ee8; }
.map-legend__area { width: 28px; height: 12px; border: 1.5px solid #4967f2; border-radius: 4px; background: rgba(73,103,242,.16); }
.map-legend__selected { width: 28px; height: 12px; border: 3px solid #fff; border-radius: 4px; background: #8fa0f2; box-shadow: 0 0 0 1px #7789d8; }
</style>
