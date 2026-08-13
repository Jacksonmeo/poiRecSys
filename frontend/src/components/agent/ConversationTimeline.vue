<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue"
import type { AgentChatMessage } from "@/types/agent"
import ToolTimeline from "./ToolTimeline.vue"

const props = defineProps<{ messages: AgentChatMessage[] }>()
const timelineRef = ref<HTMLDivElement>()
let scrollFrame: number | undefined

/** 将对话滚动到最新消息，避免流式输出时视图停留在旧内容。 */
const scrollToLatest = () => {
  if (scrollFrame !== undefined) window.cancelAnimationFrame(scrollFrame)
  scrollFrame = window.requestAnimationFrame(() => {
    const timeline = timelineRef.value
    if (timeline) timeline.scrollTop = timeline.scrollHeight
    scrollFrame = undefined
  })
}

/** 等待 DOM 更新后再执行滚动，确保新消息已经进入布局。 */
const scheduleScrollToLatest = async () => {
  await nextTick()
  scrollToLatest()
}

/** 生成对话内容指纹，用于触发流式消息变化后的自动滚动。 */
const latestActivity = () => {
  const latest = props.messages[props.messages.length - 1]
  return [
    props.messages.length,
    latest?.content.length ?? 0,
    latest?.taskStatus ?? "",
    latest?.toolCalls?.length ?? 0,
    latest?.executions?.length ?? 0,
    latest?.executions?.map((item) => item.status).join(",") ?? "",
    latest?.mapLayerCount ?? -1,
  ].join("|")
}

watch(latestActivity, scheduleScrollToLatest, { flush: "post" })
onMounted(scheduleScrollToLatest)
onBeforeUnmount(() => {
  if (scrollFrame !== undefined) window.cancelAnimationFrame(scrollFrame)
})
</script>

<template>
  <div ref="timelineRef" class="conversation-timeline" aria-live="polite">
    <article
      v-for="(message, index) in messages"
      :key="index"
      class="conversation-item"
      :class="`is-${message.role}`"
    >
      <template v-if="message.role === 'user'">
        <div class="conversation-item__meta"><span>你</span></div>
        <p class="conversation-item__question">{{ message.content }}</p>
      </template>
      <template v-else>
        <div class="conversation-item__meta is-agent">
          <span>GeoAgent</span>
          <small>{{ message.taskStatus === 'running' ? '正在工作' : '分析任务' }}</small>
        </div>
        <ToolTimeline v-if="message.taskStatus" :message="message" />
        <div v-if="message.content" class="conversation-item__answer">
          <span>分析结论</span>
          <p>{{ message.content }}</p>
        </div>
        <div v-if="message.artifacts?.length" class="conversation-item__artifact">
          <span><i />结构化分析结果</span>
          <strong>选址空间证据</strong>
          <small>{{ message.artifacts[0].data.candidate_areas.length }} 个候选区域 · 已同步至地图与结果工作台</small>
        </div>
      </template>
    </article>
  </div>
</template>

<style scoped>
.conversation-timeline { display: flex; flex: 1; min-height: 0; flex-direction: column; gap: 14px; padding: 14px; overflow-y: auto; scrollbar-color: #cbd8e7 transparent; scrollbar-width: thin; }
.conversation-item { display: grid; gap: 6px; }
.conversation-item__meta { display: flex; align-items: center; justify-content: flex-end; gap: 7px; color: #627087; font-size: var(--agent-font-meta, 10px); }
.conversation-item__meta span { font-weight: 750; }
.conversation-item__meta small { color: #8491a5; font-size: var(--agent-font-meta, 10px); }
.conversation-item__meta.is-agent { justify-content: flex-start; }
.conversation-item__meta.is-agent span { color: #4864d8; }
.conversation-item__question { max-width: 88%; justify-self: end; margin: 0; padding: 11px 13px; border-radius: 12px 12px 3px 12px; color: #fff; background: linear-gradient(145deg, #5874f5, #405ee8); box-shadow: 0 7px 16px rgba(65,92,221,.17); font-size: var(--agent-font-body, 14px); line-height: 1.65; }
.conversation-item__answer { margin-top: 1px; padding: 10px 11px; border: 1px solid #e1e8f2; border-radius: 12px; background: #fff; }
.conversation-item__answer > span { color: #5870b3; font-size: var(--agent-font-meta, 10px); font-weight: 750; }
.conversation-item__answer p { margin: 5px 0 0; color: #3f4f68; font-size: var(--agent-font-body, 14px); line-height: 1.7; white-space: pre-wrap; }
.conversation-item__artifact { display: grid; gap: 3px; padding: 10px 11px; border: 1px solid #cfdafa; border-radius: 12px; background: linear-gradient(135deg,#f7f9ff,#eff4ff); }
.conversation-item__artifact span { display: flex; align-items: center; gap: 6px; color: #6078bc; font-size: 11px; letter-spacing: .06em; }
.conversation-item__artifact span i { width: 6px; height: 6px; border-radius: 2px; background: #4967f2; }
.conversation-item__artifact strong { color: #2d3d61; font-size: 13px; }
.conversation-item__artifact small { color: #78869c; font-size: 11px; }
</style>
