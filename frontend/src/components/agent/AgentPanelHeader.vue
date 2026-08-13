<script setup lang="ts">
import { Delete } from "@element-plus/icons-vue"

defineProps<{ working: boolean }>()
const emit = defineEmits<{ clear: [] }>()
</script>

<template>
  <div class="panel-header">
    <div class="panel-header__identity">
      <span class="panel-header__avatar" aria-hidden="true"><span class="avatar-mouth"></span></span>
      <div class="panel-header__meta">
        <strong>空间决策 Agent</strong>
        <span class="meta" :class="{ 'is-working': working }">
          当前会话：<span class="dot"></span>{{ working ? "正在分析" : "已连接" }}
        </span>
      </div>
    </div>
    <el-button class="panel-header__clear" plain size="small" :disabled="working" @click="emit('clear')">
      <el-icon><Delete /></el-icon>清空会话
    </el-button>
  </div>
</template>

<style scoped>
.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  height: 68px;
  padding: 0 14px;
  border-bottom: 1px solid #e6edf6;
}

.panel-header__identity { display: flex; align-items: center; gap: 12px; min-width: 0; }

.panel-header__avatar {
  position: relative;
  display: grid;
  width: 42px;
  height: 42px;
  flex: none;
  place-items: center;
  overflow: hidden;
  border: 3px solid transparent;
  border-radius: 50%;
  background: radial-gradient(circle at 50% 42%, #38d7ff 0 9%, #11315b 11% 24%, #091728 26% 62%, #8e76ff 64%);
  box-shadow: inset 0 -7px 12px rgba(0,0,0,.28), 0 0 18px rgba(108,95,255,.45), 0 5px 13px rgba(31, 53, 91, .16);
}

.panel-header__avatar::before,
.panel-header__avatar::after {
  position: absolute;
  top: 16px;
  width: 5px;
  height: 5px;
  content: "";
  border-radius: 50%;
  background: #65e9ff;
  box-shadow: 0 0 7px #4edfff;
}
.panel-header__avatar::before { left: 10px; }
.panel-header__avatar::after { right: 10px; }
.panel-header__avatar .avatar-mouth { position: absolute; bottom: 7px; width: 10px; height: 3px; border-radius: 50%; background: #3eb9e3; }

.panel-header__meta { min-width: 0; }
.panel-header__meta strong, .panel-header__meta .meta { display: block; white-space: nowrap; }
.panel-header__meta strong { color: #152039; font-size: 16px; font-weight: 720; }
.panel-header__meta .meta { margin-top: 4px; color: #748198; font-size: var(--agent-font-secondary, 13px); }
.panel-header__meta .meta .dot { display: inline-block; width: 6px; height: 6px; margin: 0 5px 1px 1px; border-radius: 50%; background: #33c58b; box-shadow: 0 0 0 3px rgba(51, 197, 139, .1); }
.panel-header__meta .meta.is-working .dot { background: #27b6ed; box-shadow: 0 0 0 3px rgba(39, 182, 237, .1); animation: pulse 1.3s ease-in-out infinite; }

.panel-header__clear { height: 36px; padding-inline: 11px; border-color: #dae4ef; border-radius: 9px; color: #6a778d; background: #fff; font-size: 13px; }

@keyframes pulse { 50% { opacity: .35; transform: scale(.75); } }
</style>
