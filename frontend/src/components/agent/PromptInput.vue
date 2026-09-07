<script setup lang="ts">
import { Coin, DataAnalysis, Promotion } from "@element-plus/icons-vue"
import { nextTick, ref, watch } from "vue"

const props = defineProps<{ disabled?: boolean }>()
const emit = defineEmits<{ send: [message: string] }>()
const text = ref("")
const inputRef = ref<{ focus: () => void }>()

/** 在输入框可用时聚焦，提升打开对话框后的输入效率。 */
const focusInput = async () => {
  await nextTick()
  if (!props.disabled) inputRef.value?.focus()
}

watch(
  () => props.disabled,
  (disabled) => {
    if (!disabled) void focusInput()
  },
  { flush: "post", immediate: true },
)

/** 校验并提交当前输入，同时清空输入框。 */
const submit = () => {
  const message = text.value.trim()
  if (!message || props.disabled) return
  emit("send", message)
  text.value = ""
}

const quickPrompts = [
  { label: "POI 搜索", prompt: "帮我查找东京的热门 POI", icon: Coin },
  { label: "热力分析", prompt: "分析东京中心 POI 密度分布", icon: DataAnalysis },
  { label: "地点推荐", prompt: "给我推荐 3 个地点", icon: Promotion },
  // { label: "轨迹分析", prompt: "查看用户轨迹", icon: Connection },
]

/** 发送快捷提问卡片中的预设问题。 */
const sendQuick = (prompt: string) => {
  if (!props.disabled) emit("send", prompt)
}
</script>

<template>
  <div class="prompt-area">
    <div class="prompt-input">
      <el-input
        ref="inputRef"
        v-model="text"
        type="textarea"
        :autosize="{ minRows: 2, maxRows: 4 }"
        :disabled="disabled"
        resize="none"
        placeholder="向 GeoAgent 提问……例如：分析东京咖啡店分布"
        @keydown.enter.exact.prevent="submit"
      />
      <button
        class="prompt-input__send"
        type="button"
        :disabled="disabled || !text.trim()"
        aria-label="发送消息"
        @click="submit"
      >
        <el-icon><Promotion /></el-icon>
      </button>
    </div>

    <div class="prompt-input__quick">
      <button
        v-for="item in quickPrompts"
        :key="item.label"
        type="button"
        :disabled="disabled"
        @click="sendQuick(item.prompt)"
      >
        <el-icon><component :is="item.icon" /></el-icon>{{ item.label }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.prompt-area { padding: 12px 13px 13px; border-top: 1px solid #e8eef5; background: rgba(255,255,255,.98); }
.prompt-input { position: relative; min-height: 86px; padding: 14px 60px 12px 14px; border: 1.5px solid #6780ff; border-radius: 18px; background: #fff; box-shadow: 0 8px 24px rgba(65,88,210,.11); transition: border-color .2s ease, box-shadow .2s ease; }
.prompt-input:focus-within { border-color: #4564f4; box-shadow: 0 0 0 4px rgba(73,103,242,.12), 0 12px 28px rgba(65,88,210,.14); }
.prompt-input :deep(.el-textarea__inner) { min-height: 54px !important; padding: 0; border: 0; color: #344054; background: transparent; box-shadow: none; font-size: 15px; line-height: 1.6; }
.prompt-input :deep(.el-textarea__inner::placeholder) { color: #9aa6b9; }
.prompt-input__send { position: absolute; right: 13px; bottom: 13px; display: grid; width: 42px; height: 42px; place-items: center; border: 0; border-radius: 50%; color: #fff; background: linear-gradient(145deg, #4167f4, #3156e9); box-shadow: 0 8px 18px rgba(49, 86, 233, .28); font-size: 19px; cursor: pointer; transition: transform .18s ease, opacity .18s ease; }
.prompt-input__send:hover:not(:disabled) { transform: translateY(-1px) scale(1.03); }
.prompt-input__send:disabled { cursor: not-allowed; opacity: .42; box-shadow: none; }
.prompt-input__quick { display: flex; gap: 7px; margin-top: 10px; overflow-x: auto; scrollbar-width: none; }
.prompt-input__quick::-webkit-scrollbar { display: none; }
.prompt-input__quick button { display: inline-flex; height: 34px; flex: none; align-items: center; gap: 5px; padding: 0 11px; border: 1px solid #e1e8f1; border-radius: 999px; color: #5f6e84; background: #fbfcfe; font-size: var(--agent-font-secondary, 13px); cursor: pointer; }
.prompt-input__quick button:hover:not(:disabled) { border-color: #bdcaf2; color: #4564e9; background: #f5f7ff; }
</style>
