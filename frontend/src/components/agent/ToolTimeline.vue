<script setup lang="ts">
import { Loading } from "@element-plus/icons-vue"
import { computed } from "vue"
import { TOOL_META, formatToolArgs, formatToolResult } from "@/composables/useToolExecution"
import type { AgentChatMessage, ToolStatus } from "@/types/agent"

const props = defineProps<{ message: AgentChatMessage }>()
interface Step { id: string; label: string; hint: string; status: ToolStatus; chips: string[]; result: string }

/** 将消息中的工具执行记录转换为可视化任务步骤。 */
const steps = computed<Step[]>(() => {
  const executions = props.message.executions ?? []
  const understanding: ToolStatus = props.message.taskStatus === "error"
    ? "error" : executions.length || props.message.taskStatus === "success" ? "success" : "running"
  const items: Step[] = [{
    id: "understanding", label: "理解任务与分析范围", hint: "Agent 分析",
    status: understanding, chips: [], result: "",
  }]
  executions.forEach((execution, index) => {
    const meta = TOOL_META[execution.tool] ?? { label: execution.tool, hint: "工具" }
    items.push({
      id: `${execution.tool}-${index}`, label: meta.label, hint: meta.hint,
      status: execution.status, chips: formatToolArgs(execution.args), result: formatToolResult(execution.result),
    })
  })
  if (executions.length) {
    const pending = props.message.taskStatus !== "error" && props.message.mapLayerCount === undefined
    items.push({
      id: "output",
      label: props.message.artifacts?.length ? "同步结构化结果与地图证据" : "整理空间分析结果",
      hint: props.message.artifacts?.length ? "结构化输出" : "地图画布",
      status: props.message.taskStatus === "error" ? "error" : pending ? "pending" : "success",
      chips: props.message.artifacts?.length ? [`${props.message.artifacts.length} 份结果`] : [],
      result: "",
    })
  }
  return items
})

const statusLabel: Record<ToolStatus, string> = {
  pending: "等待中", running: "执行中", success: "已完成", error: "失败",
}
</script>

<template>
  <div class="tool-timeline" aria-label="Agent 任务执行过程">
    <div v-for="step in steps" :key="step.id" class="tool-step" :class="`is-${step.status}`">
      <span class="tool-step__rail"><i>
        <el-icon v-if="step.status === 'running'" class="is-loading"><Loading /></el-icon>
        <template v-else-if="step.status === 'success'">✓</template>
        <template v-else-if="step.status === 'error'">!</template>
      </i></span>
      <div class="tool-step__content">
        <div class="tool-step__head">
          <span><strong>{{ step.label }}</strong><small>{{ step.hint }}</small></span>
          <em>{{ statusLabel[step.status] }}</em>
        </div>
        <div v-if="step.chips.length" class="tool-step__chips"><span v-for="chip in step.chips" :key="chip">{{ chip }}</span></div>
        <p v-if="step.result">{{ step.result }}</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.tool-timeline { padding: 10px 11px; border: 1px solid #dfe8f2; border-radius: 13px; background: linear-gradient(145deg,#fbfdff,#f6f9fd); }
.tool-step { display: grid; min-height: 43px; grid-template-columns: 22px minmax(0,1fr); gap: 8px; }
.tool-step:last-child { min-height: 28px; }
.tool-step__rail { position: relative; display: flex; justify-content: center; }
.tool-step__rail::after { position: absolute; top: 22px; bottom: 0; width: 1px; content: ""; background: #d9e3ef; }
.tool-step:last-child .tool-step__rail::after { display: none; }
.tool-step__rail i { position: relative; z-index: 1; display: grid; width: 18px; height: 18px; place-items: center; border: 1px solid #cbd6e3; border-radius: 50%; color: transparent; background: #fff; font-size: 10px; font-style: normal; }
.tool-step.is-success .tool-step__rail i { border-color: #39bb88; color: #fff; background: #39bb88; }
.tool-step.is-running .tool-step__rail i { border-color: #3a8cf3; color: #3a8cf3; box-shadow: 0 0 0 4px rgba(58,140,243,.09); }
.tool-step.is-error .tool-step__rail i { border-color: #e85f5a; color: #fff; background: #e85f5a; }
.tool-step__content { min-width: 0; padding-bottom: 9px; }
.tool-step__head { display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; }
.tool-step__head strong,.tool-step__head small { display: block; }
.tool-step__head strong { color: #35435b; font-size: 13px; }
.tool-step__head small { margin-top: 2px; color: #8491a5; font-size: 11px; }
.tool-step__head em { flex: none; color: #8794a7; font-size: 11px; font-style: normal; }
.tool-step.is-success em { color: #259b70; }.tool-step.is-running em { color: #2e79df; }.tool-step.is-error em { color: #d64b47; }
.tool-step__chips { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 6px; }
.tool-step__chips span { padding: 3px 7px; border: 1px solid #d9e4f3; border-radius: 999px; color: #5570a8; background: #f3f7ff; font-family: var(--font-mono); font-size: 11px; }
.tool-step__content p { margin: 5px 0 0; color: #68778e; font-size: 11px; }
</style>
