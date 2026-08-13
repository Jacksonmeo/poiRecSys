<script setup lang="ts">
import { CoffeeCup, DataAnalysis } from "@element-plus/icons-vue"

defineProps<{ disabled?: boolean }>()
const emit = defineEmits<{ select: [prompt: string] }>()

const prompts = [
  {
    category: "商业选址分析",
    prompt: "帮我分析东京适合开咖啡店的位置",
    context: "POI · 密度 · 推荐",
    icon: CoffeeCup,
    tone: "amber",
  },
  {
    category: "城市热点洞察",
    prompt: "分析东京中心的 POI 密度热点",
    context: "PostGIS · 热力图",
    icon: DataAnalysis,
    tone: "cyan",
  },
]
</script>

<template>
  <section class="prompt-cards" aria-labelledby="prompt-card-title">
    <div class="prompt-cards__head">
      <span id="prompt-card-title">从一个分析任务开始</span>
      <span class="meta">示例问题</span>
    </div>
    <button
      v-for="item in prompts"
      :key="item.category"
      class="prompt-cards__card"
      type="button"
      :disabled="disabled"
      @click="emit('select', item.prompt)"
    >
      <span class="prompt-cards__icon" :class="`is-${item.tone}`">
        <el-icon><component :is="item.icon" /></el-icon>
      </span>
      <span class="prompt-cards__copy">
        <span class="meta">{{ item.category }}</span>
        <strong>{{ item.prompt }}</strong>
        <span class="context">{{ item.context }}</span>
      </span>
      <span class="arrow">→</span>
    </button>
  </section>
</template>

<style>
.prompt-cards { display: grid; gap: 8px; }
.prompt-cards__head { display: flex; align-items: center; justify-content: space-between; color: #33425d; font-size: var(--agent-font-body, 12px); font-weight: 750; }
.prompt-cards__head .meta { color: #8492a7; font-family: var(--font-mono); font-size: var(--agent-font-meta, 10px); font-weight: 500; }
.prompt-cards__card { display: grid; width: 100%; min-height: 74px; grid-template-columns: 38px minmax(0, 1fr) 16px; align-items: center; gap: 10px; padding: 10px 11px; border: 1px solid #dce6f2; border-radius: 13px; color: #34425b; background: linear-gradient(105deg, #fff, #f7faff); text-align: left; cursor: pointer; appearance: none; transition: .2s ease; }
.prompt-cards__card:hover:not(:disabled) { border-color: #aebff2; box-shadow: 0 10px 24px rgba(56,78,145,.1); transform: translateY(-1px); }
.prompt-cards__card:disabled { cursor: not-allowed; opacity: .5; }
.prompt-cards__icon { display: grid; width: 38px; height: 38px; place-items: center; border-radius: 11px; font-size: 18px; }
.prompt-cards__icon.is-amber { color: #cb720c; background: #fff2df; }
.prompt-cards__icon.is-cyan { color: #078caf; background: #e7f8fc; }
.prompt-cards__copy { min-width: 0; }
.prompt-cards__copy .meta, .prompt-cards__copy strong, .prompt-cards__copy .context { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.prompt-cards__copy .meta { color: #60719c; font-size: var(--agent-font-meta, 10px); font-weight: 700; }
.prompt-cards__copy strong { margin-top: 3px; color: #263650; font-size: var(--agent-font-body, 12px); }
.prompt-cards__copy .context { margin-top: 4px; color: #8491a5; font-family: var(--font-mono); font-size: var(--agent-font-meta, 10px); font-style: normal; }
.prompt-cards__card > .arrow { color: #7790ce; font-size: 14px; font-style: normal; }
</style>
