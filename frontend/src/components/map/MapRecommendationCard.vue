<script setup lang="ts">
import { computed } from "vue"
import { getPoiDisplayName } from "@/utils/poi"
import type { MapPoint } from "@/types/map"

const props = defineProps<{ point: MapPoint }>()
const emit = defineEmits<{ select: [point: MapPoint] }>()
/** 将后端推荐理由拆成卡片中的逐条说明。 */
const reasons = computed(() => props.point.reason?.split("；").filter(Boolean) ?? [])
</script>

<template>
  <aside class="recommendation-card">
    <div class="recommendation-card__head">
      <span><small>首选推荐</small><strong>推荐地点</strong></span>
      <i>★</i>
    </div>
    <button type="button" @click="emit('select', point)">
      <span class="recommendation-card__rank">#1</span>
      <span>
        <strong>{{ getPoiDisplayName(point) }}</strong>
        <small>{{ point.venue_category || "东京" }}</small>
      </span>
      <em>{{ typeof point.score === "number" ? point.score.toFixed(2) : "--" }}</em>
    </button>
    <div v-if="reasons.length" class="recommendation-card__reasons">
      <span>推荐依据</span>
      <p v-for="reason in reasons" :key="reason">{{ reason }}</p>
    </div>
    <p v-else class="recommendation-card__empty">暂无可用解释信息</p>
  </aside>
</template>

<style scoped>
.recommendation-card { width: 232px; padding: 12px; border: 1px solid rgba(208,220,234,.96); border-radius: 14px; background: rgba(255,255,255,.95); box-shadow: 0 14px 34px rgba(46,66,108,.14); backdrop-filter: blur(14px); }
.recommendation-card__head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
.recommendation-card__head small, .recommendation-card__head strong { display: block; }
.recommendation-card__head small { color: #6f82bc; font-family: var(--font-mono); font-size: 6px; letter-spacing: .08em; }
.recommendation-card__head strong { margin-top: 2px; color: #3b4960; font-size: 9px; }
.recommendation-card__head i { display: grid; width: 25px; height: 25px; place-items: center; border-radius: 9px; color: #fff; background: linear-gradient(145deg,#9969f2,#7654dd); box-shadow: 0 6px 13px rgba(118,84,221,.24); font-size: 10px; font-style: normal; }
.recommendation-card > button { display: grid; width: 100%; grid-template-columns: 34px minmax(0,1fr) auto; align-items: center; gap: 8px; padding: 9px; border: 1px solid #e1e7f2; border-radius: 11px; color: #38465d; background: #f9faff; text-align: left; cursor: pointer; }
.recommendation-card > button:hover { border-color: #b9c5ed; }
.recommendation-card__rank { display: grid; width: 34px; height: 34px; place-items: center; border-radius: 10px; color: #fff; background: linear-gradient(145deg,#5574f3,#7859e5); font-family: var(--font-mono); font-size: 9px; }
.recommendation-card button > span:nth-child(2) { min-width: 0; }
.recommendation-card button strong, .recommendation-card button small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.recommendation-card button strong { font-size: 9px; }
.recommendation-card button small { margin-top: 3px; color: #96a1b2; font-size: 7px; }
.recommendation-card button em { color: #7557de; font-family: var(--font-mono); font-size: 10px; font-style: normal; }
.recommendation-card__reasons { margin-top: 9px; }
.recommendation-card__reasons > span { color: #65728a; font-size: 8px; font-weight: 700; }
.recommendation-card__reasons p { margin: 5px 0 0; color: #78859a; font-size: 7px; line-height: 1.45; }
.recommendation-card__reasons p::before { margin-right: 5px; color: #2caf7b; content: "✓"; }
.recommendation-card__empty { margin: 8px 0 0; color: #9ba6b7; font-size: 7px; }
</style>
