<script setup lang="ts">
import { Location } from "@element-plus/icons-vue"
import type { AgentChatMessage } from "@/types/agent"
import AgentPanelHeader from "./AgentPanelHeader.vue"
import CapabilitySection from "./CapabilitySection.vue"
import ConversationTimeline from "./ConversationTimeline.vue"
import ExamplePrompts from "./ExamplePrompts.vue"
import PromptInput from "./PromptInput.vue"

defineProps<{
  messages: AgentChatMessage[]
  sending: boolean
}>()

defineEmits<{
  clear: []
  send: [message: string]
}>()
</script>

<template>
  <div class="agent-workspace">
    <AgentPanelHeader :working="sending" @clear="$emit('clear')" />
    <div class="agent-workspace__body">
      <div v-if="!messages.length" class="agent-workspace__start">
        <div class="agent-workspace__welcome">
          <span><el-icon><Location /></el-icon></span>
          <div>
            <span class="meta">空间决策工作台</span>
            <h2>从一个选址问题开始</h2>
            <p>GeoAgent 会调用空间分析工具，并将结构化证据同步到地图和结果工作台。</p>
          </div>
        </div>
        <CapabilitySection :disabled="sending" @select="$emit('send', $event)" />
        <ExamplePrompts :disabled="sending" @select="$emit('send', $event)" />
      </div>
      <ConversationTimeline v-else :messages="messages" />
    </div>
    <PromptInput :disabled="sending" @send="$emit('send', $event)" />
  </div>
</template>

<style scoped>
.agent-workspace { --agent-font-meta: 12px; --agent-font-secondary: 13px; --agent-font-body: 14px; display: flex; height: 100%; min-height: 0; flex-direction: column; background: rgba(255,255,255,.97); }
.agent-workspace__body { display: flex; flex: 1; min-height: 0; flex-direction: column; }
.agent-workspace__start { display: flex; flex: 1; min-height: 0; flex-direction: column; gap: 16px; padding: 16px 14px 12px; overflow-y: auto; }
.agent-workspace__welcome { display: flex; align-items: flex-start; gap: 11px; padding: 2px; }
.agent-workspace__welcome > span { display: grid; width: 37px; height: 37px; flex: none; place-items: center; border: 1px solid #dae5ff; border-radius: 11px; color: #4967f2; background: linear-gradient(145deg,#edf2ff,#edf9ff); font-size: 18px; box-shadow: 0 7px 16px rgba(66,89,170,.08); }
.agent-workspace__welcome .meta { color: #6f86bf; font-size: var(--agent-font-meta); font-weight: 700; letter-spacing: .07em; }
.agent-workspace__welcome h2 { margin: 3px 0 4px; color: #19263e; font-size: 21px; font-weight: 760; }
.agent-workspace__welcome p { margin: 0; color: #748198; font-size: var(--agent-font-secondary); line-height: 1.55; }
@media (max-height: 760px) { .agent-workspace__start { gap: 11px; padding-top: 11px; } }
</style>
