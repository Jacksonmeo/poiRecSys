<script setup lang="ts">
import { Connection, DataAnalysis, Location, Promotion, Search } from "@element-plus/icons-vue"

defineProps<{ disabled?: boolean }>()
const emit = defineEmits<{ select: [prompt: string] }>()

const capabilities = [
  { title: "商业选址", hint: "候选区指标与迁移证据", prompt: "对比新宿、涩谷、银座和池袋的咖啡店选址条件", icon: Location, tone: "amber" },
  { title: "POI 查询", hint: "按类别与空间范围检索", prompt: "帮我查询东京的 Coffee Shop", icon: Search, tone: "blue" },
  { title: "空间分析", hint: "发现密度、热点与聚集", prompt: "分析东京中心区域的 POI 密度，grid=10", icon: DataAnalysis, tone: "cyan" },
  { title: "地点推荐", hint: "基于历史序列预测去向", prompt: "给我推荐 3 个地点", icon: Promotion, tone: "violet" },
  { title: "轨迹分析", hint: "理解用户移动与停留", prompt: "查看一个用户的历史轨迹", icon: Connection, tone: "green" },
]
</script>

<template>
  <section class="capabilities" aria-labelledby="capability-title">
    <div class="capabilities__head"><span id="capability-title">空间决策能力</span><span class="meta">5 个工具已连接</span></div>
    <div class="capabilities__grid">
      <button v-for="item in capabilities" :key="item.title" type="button" :disabled="disabled" @click="emit('select', item.prompt)">
        <span class="capabilities__icon" :class="`is-${item.tone}`"><el-icon><component :is="item.icon" /></el-icon></span>
        <span><strong>{{ item.title }}</strong><span class="meta">{{ item.hint }}</span></span><span class="arrow">→</span>
      </button>
    </div>
  </section>
</template>

<style scoped>
.capabilities__head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 9px; color: #33425d; font-size: 14px; font-weight: 750; }
.capabilities__head .meta { color: #8492a7; font-size: 13px; font-weight: 500; }
.capabilities__grid { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 8px; }
.capabilities button { display: grid; min-height: 66px; grid-template-columns: 32px minmax(0,1fr) 10px; align-items: center; gap: 8px; padding: 9px; border: 1px solid #dde7f2; border-radius: 12px; color: #30405d; background: linear-gradient(145deg,#fff,#f7faff); text-align: left; cursor: pointer; transition: .18s ease; }
.capabilities button:first-child { grid-column: 1 / -1; border-color: #d5ddfa; background: linear-gradient(105deg,#fffaf2,#f5f7ff); }
.capabilities button:hover:not(:disabled) { border-color: #aabdf4; box-shadow: 0 9px 20px rgba(56,78,145,.1); transform: translateY(-1px); }
.capabilities button:disabled { cursor: not-allowed; opacity: .5; }
.capabilities button > span:nth-child(2) { min-width: 0; }
.capabilities strong,.capabilities button .meta { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.capabilities strong { font-size: 14px; }.capabilities button .meta { margin-top: 4px; color: #7c899d; font-size: 12px; }
.capabilities button .arrow { color: #8d9bb0; font-size: 12px; font-style: normal; }
.capabilities__icon { display: grid; width: 32px; height: 32px; place-items: center; border-radius: 10px; font-size: 16px; }
.is-blue { color: #4967f2; background: #edf1ff; }.is-cyan { color: #0b9ec7; background: #e8f9fd; }
.is-violet { color: #8058e8; background: #f1edff; }.is-green { color: #15966c; background: #e9f8f2; }.is-amber { color: #c87914; background: #fff0d9; }
</style>
