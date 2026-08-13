<script setup lang="ts">
import { computed } from "vue"
import { getPoiDisplayName } from "@/utils/poi"
import type { MapPoint } from "@/types/map"

const props = defineProps<{ points: MapPoint[] }>()
const emit = defineEmits<{ select: [point: MapPoint] }>()

/** 按 rank 排序并限制地图洞察卡展示的点位数量。 */
const ranked = computed(() => [...props.points]
  .sort((a, b) => (a.rank ?? 999) - (b.rank ?? 999))
  .slice(0, 3))
/** 判断当前点位中是否存在可展示的推荐分数。 */
const hasScores = computed(() => ranked.value.some((point) => typeof point.score === "number"))
</script>

<template>
  <aside v-if="ranked.length" class="insight-card">
    <div class="insight-card__head">
      <span><i></i><strong>{{ hasScores ? "推荐洞察" : "POI 结果" }}</strong></span>
      <small>显示 {{ ranked.length }} 项</small>
    </div>
    <button
      v-for="(point, index) in ranked"
      :key="point.venue_id || index"
      type="button"
      @click="emit('select', point)"
    >
      <i :class="`rank-${index + 1}`">{{ point.rank ?? index + 1 }}</i>
      <span>
        <strong>{{ getPoiDisplayName(point) }}</strong>
        <small>{{ point.venue_category || "东京 POI" }}</small>
      </span>
      <em v-if="typeof point.score === 'number'">{{ point.score.toFixed(2) }}</em>
      <em v-else>定位</em>
    </button>
    <p>点击候选可定位到地图</p>
  </aside>
</template>

<style scoped>
.insight-card { width: 226px; padding: 11px 12px 9px; border: 1px solid rgba(208,220,234,.96); border-radius: 14px; background: rgba(255,255,255,.95); box-shadow: 0 14px 34px rgba(46,66,108,.14); backdrop-filter: blur(14px); }
.insight-card__head { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 7px; padding-bottom: 8px; border-bottom: 1px solid #edf1f6; }
.insight-card__head > span { display: inline-flex; min-width: 0; align-items: center; gap: 7px; }
.insight-card__head i { width: 7px; height: 7px; flex: none; border-radius: 2px; background: #4b6bf0; box-shadow: 0 0 0 4px rgba(75,107,240,.1); }
.insight-card__head strong { overflow: hidden; color: #344159; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.insight-card__head small { flex: none; color: #9ba6b7; font-size: 10px; }
.insight-card > button { display: flex; width: 100%; min-height: 38px; align-items: center; gap: 8px; padding: 5px 2px; border: 0; border-bottom: 1px solid #f0f3f7; color: #435169; background: transparent; text-align: left; cursor: pointer; }
.insight-card > button:hover { background: #f7f9ff; }
.insight-card > button > i { display: grid; width: 20px; height: 20px; flex: none; place-items: center; border-radius: 50%; color: #fff; background: #7558e5; font-size: 8px; font-style: normal; }
.insight-card > button > i.rank-2 { background: #e55d58; }
.insight-card > button > i.rank-3 { background: #edae2d; }
.insight-card > button > span { min-width: 0; flex: 1; }
.insight-card button strong, .insight-card button small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.insight-card button strong { font-size: 12px; }
.insight-card button small { margin-top: 3px; color: #9aa5b6; font-size: 10px; }
.insight-card button em { flex: none; color: #596fe0; font-size: 11px; font-style: normal; }
.insight-card > p { margin: 7px 0 0; color: #a0a9b8; font-size: 10px; }
</style>
