<script setup lang="ts">
import { computed } from "vue"
import { storeToRefs } from "pinia"
import AgentPanel from "@/components/workspace/AgentPanel.vue"
import MapLayerRenderer from "@/components/map/MapLayerRenderer.vue"
import { useWorkspaceStore, type WorkspaceTask } from "@/stores/workspace"

const workspace = useWorkspaceStore()
const { activeArtifact, activeTask, agentOpen, mapLayers, selectedArea, sending } = storeToRefs(workspace)
const stageLabels: Record<WorkspaceTask["stage"], string> = {
  understanding: "理解任务", tool: "调用工具", evidence: "整理证据", complete: "已完成", error: "执行失败",
}
/** 将工作台内部任务阶段转换成地图底部的中文状态文案。 */
const activeStage = computed(() => activeTask.value ? stageLabels[activeTask.value.stage] : "")
</script>

<template>
  <section class="spatial-canvas" data-testid="spatial-canvas" aria-label="空间证据地图">
    <div class="spatial-canvas__map">
      <MapLayerRenderer
        :layers="mapLayers"
        :artifact="activeArtifact"
        :selected-area="selectedArea"
        :working="sending"
        @select-area="workspace.selectArea"
      />
    </div>
    <footer v-if="activeTask" class="spatial-canvas__task">
      <span>当前任务</span>
      <p>{{ activeTask.prompt }}</p>
      <span class="state">{{ activeStage }}</span>
    </footer>
    <button class="agent-orb" type="button" aria-label="打开 Agent 对话" @click="workspace.toggleAgent">
      <span class="agent-orb__halo" aria-hidden="true" />
      <span class="agent-orb__face" aria-hidden="true"><span class="orb-eye"></span><span class="orb-eye orb-eye--right"></span><span class="orb-mouth"></span></span>
      <span class="agent-orb__label">Agent</span>
    </button>
    <Transition name="agent-dialog">
      <div v-if="agentOpen" class="agent-dialog" role="dialog" aria-modal="true" aria-label="Agent 对话" @click.self="workspace.closeAgent">
        <div class="agent-dialog__panel">
          <button class="agent-dialog__close" type="button" aria-label="关闭 Agent 对话" @click="workspace.closeAgent">×</button>
          <AgentPanel />
        </div>
      </div>
    </Transition>
  </section>
</template>

<style scoped>
.spatial-canvas { position: relative; display: grid; min-width: 0; min-height: 0; grid-template-rows: minmax(0, 1fr); background: #dce7f1; }
.spatial-canvas__map { min-height: 0; overflow: hidden; }
.spatial-canvas__task { position: absolute; z-index: 4; bottom: 18px; left: 112px; display: grid; width: min(520px, max(240px, calc(100% - 352px))); grid-template-columns: auto minmax(0,1fr) auto; align-items: center; gap: 12px; padding: 11px 14px; border: 1px solid rgba(201,216,230,.92); border-radius: 13px; background: rgba(249,252,255,.93); box-shadow: 0 10px 24px rgba(33,53,82,.12); backdrop-filter: blur(12px); }
.spatial-canvas__task span { color: #7185a2; font-family: var(--font-mono); font-size: 10px; letter-spacing: .08em; }
.spatial-canvas__task p { margin: 0; overflow: hidden; color: #3d4c61; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.spatial-canvas__task .state { color: #356f99; font-size: 11px; font-style: normal; }
.agent-orb { position: absolute; z-index: 8; bottom: 82px; left: 22px; display: grid; width: 76px; height: 76px; place-items: center; border: 0; border-radius: 50%; background: transparent; cursor: pointer; filter: drop-shadow(0 14px 24px rgba(62,76,201,.28)); }
.agent-orb__halo { position: absolute; inset: 0; border-radius: 50%; background: conic-gradient(from 30deg, #31d7ff, #7a5cff, #ff5fcf, #ffd45e, #31d7ff); opacity: .88; animation: orb-spin 7s linear infinite; }
.agent-orb__halo::after { position: absolute; inset: 5px; content: ""; border-radius: inherit; background: rgba(255,255,255,.96); }
.agent-orb__face { position: relative; z-index: 1; display: grid; width: 53px; height: 53px; place-items: center; border: 2px solid rgba(255,255,255,.8); border-radius: 18px 18px 22px 22px; background: radial-gradient(circle at 50% 22%, #48eaff, #151a5d 34%, #080d2e 75%); box-shadow: inset 0 -8px 12px rgba(0,0,0,.28), 0 0 20px rgba(102,95,255,.62); animation: orb-breathe 2.4s ease-in-out infinite; }
.agent-orb__face::before { position: absolute; top: -8px; left: 24px; width: 4px; height: 9px; content: ""; border-radius: 5px; background: #8bf7ff; box-shadow: 0 0 10px #4eeeff; }
.agent-orb__face .orb-eye { position: absolute; top: 21px; width: 7px; height: 7px; content: ""; border-radius: 50%; background: #9effff; box-shadow: 0 0 8px #56eaff; }
.agent-orb__face .orb-eye { left: 14px; }.agent-orb__face .orb-eye--right { right: 14px; }
.agent-orb__face .orb-mouth { position: absolute; bottom: 12px; width: 16px; height: 4px; border-radius: 50%; background: #7a9cff; box-shadow: 0 0 8px #657aff; }
.agent-orb__label { position: absolute; right: -5px; bottom: -15px; z-index: 2; padding: 3px 7px; border: 1px solid #d7d9ff; border-radius: 999px; color: #5149bf; background: rgba(255,255,255,.92); font-size: 11px; font-weight: 750; box-shadow: 0 5px 14px rgba(60,64,160,.12); }
.agent-dialog { position: absolute; z-index: 9; inset: 0; background: rgba(24,32,70,.08); backdrop-filter: blur(2px); }
.agent-dialog__panel { position: absolute; bottom: 24px; left: 24px; width: min(520px, calc(100% - 48px)); height: min(760px, calc(100% - 64px)); overflow: hidden; border: 1px solid rgba(168,166,255,.8); border-radius: 24px; background: #fff; box-shadow: 0 0 0 1px rgba(255,255,255,.8), 0 0 24px rgba(116,85,255,.35), 0 0 68px rgba(62,212,255,.22), 0 22px 60px rgba(28,35,86,.27); }
.agent-dialog__panel::before { position: absolute; inset: -2px; z-index: -1; content: ""; border-radius: 26px; background: conic-gradient(from 120deg, rgba(61,220,255,.4), rgba(137,88,255,.6), rgba(255,110,196,.4), rgba(61,220,255,.4)); filter: blur(15px); animation: orb-spin 8s linear infinite; }
.agent-dialog__panel :deep(.workspace-agent) { height: 100%; border: 0; }
.agent-dialog__close { position: absolute; z-index: 5; top: 14px; right: 98px; display: grid; width: 32px; height: 32px; place-items: center; border: 1px solid #dce3f0; border-radius: 50%; color: #71809a; background: rgba(255,255,255,.88); font-size: 22px; line-height: 1; cursor: pointer; }
.agent-dialog__close:hover { color: #3f57ce; border-color: #bfcaf1; background: #f5f7ff; }
.agent-dialog-enter-active,.agent-dialog-leave-active { transition: opacity .24s ease; }.agent-dialog-enter-active .agent-dialog__panel,.agent-dialog-leave-active .agent-dialog__panel { transition: transform .24s ease, opacity .24s ease; }.agent-dialog-enter-from,.agent-dialog-leave-to { opacity: 0; }.agent-dialog-enter-from .agent-dialog__panel,.agent-dialog-leave-to .agent-dialog__panel { opacity: 0; transform: translateY(16px) scale(.97); }
@keyframes orb-spin { to { transform: rotate(360deg); } }
@keyframes orb-breathe { 50% { transform: translateY(-2px) scale(1.03); } }
@media (max-width: 760px) { .agent-dialog__panel { right: 12px; bottom: 18px; left: 12px; width: auto; height: min(700px, calc(100% - 90px)); } .agent-orb { right: 18px; bottom: 80px; left: auto; } .spatial-canvas__task { right: 14px; bottom: 14px; left: 14px; width: auto; } }
@media (prefers-reduced-motion: reduce) { .agent-orb__halo,.agent-orb__face,.agent-dialog__panel::before { animation: none; } }
</style>
