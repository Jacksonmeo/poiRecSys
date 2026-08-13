<script setup lang="ts">
import { computed } from "vue"
import type { AreaFlow, CandidateArea } from "@/types/siteSelection"

const props = defineProps<{
  flows: AreaFlow[]
  areas: CandidateArea[]
  selectedArea: string | null
}>()

defineEmits<{ select: [areaId: string] }>()
/** 建立区域 id 到展示名称的索引，避免模板重复查找。 */
const names = computed(() => Object.fromEntries(props.areas.map((area) => [area.area_id, area.display_name])))
/** 按迁移数量降序排列，优先展示最重要的关系。 */
const orderedFlows = computed(() => [...props.flows].sort((a, b) => b.flow_count - a.flow_count))
</script>

<template>
  <section class="flow-panel">
    <header><h4>区域迁移流</h4><span>{{ flows.length }} 条关系</span></header>
    <div v-if="orderedFlows.length" class="flow-panel__list">
      <button
        v-for="flow in orderedFlows"
        :key="`${flow.source_area}-${flow.target_area}`"
        :class="{ 'is-related': [flow.source_area, flow.target_area].includes(selectedArea || '') }"
        @click="$emit('select', flow.target_area)"
      >
        <span class="area-name">{{ names[flow.source_area] || flow.source_area }}</span><span class="arrow">→</span><span class="area-name">{{ names[flow.target_area] || flow.target_area }}</span>
        <strong>{{ flow.flow_count }}</strong>
        <span class="meta">{{ flow.unique_users }} 用户 · {{ flow.unique_sessions }} 会话</span>
      </button>
    </div>
    <p v-else>分析结果未返回区域迁移记录。</p>
  </section>
</template>

<style scoped>
.flow-panel { min-width: 0; }
header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 7px; }
h4 { margin: 0; color: #26344c; font-size: 14px; }
header span,p { color: #8b97a9; font-size: 11px; }
.flow-panel__list { display: grid; gap: 5px; max-height: 122px; overflow: auto; }
button { display: grid; min-width: 0; grid-template-columns: minmax(0,1fr) 14px minmax(0,1fr) auto; align-items: center; gap: 4px; width: 100%; padding: 7px 9px; border: 1px solid #e5ebf4; border-radius: 9px; color: #4a5870; background: #fbfcfe; text-align: left; cursor: pointer; }
button:hover,button.is-related { border-color: #cbd7ff; background: #f2f5ff; }
.area-name { min-width: 0; overflow: hidden; font-size: 12px; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.arrow { color: #8090aa; font-style: normal; text-align: center; }
strong { justify-self: end; color: #4967f2; font-family: var(--font-mono); font-size: 11px; }
.meta { grid-column: 1 / -1; color: #929eb0; font-size: 11px; }
p { margin: 0; padding: 12px; border: 1px dashed #dbe3ef; border-radius: 9px; text-align: center; }
</style>
