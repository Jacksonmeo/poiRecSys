<script setup lang="ts">
import {
  ArrowDown,
  Coin,
  Connection,
  DataAnalysis,
  Location,
  MapLocation,
  Promotion,
  Tools,
} from "@element-plus/icons-vue"
import { ref } from "vue"

const datasetOpen = ref(false)
const toolsOpen = ref(false)

const toolItems = [
  { name: "POI 查询", code: "query_poi", description: "按区域与类别检索兴趣点", icon: Location },
  { name: "空间分析", code: "spatial_density", description: "执行 PostGIS 密度与热点分析", icon: DataAnalysis },
  { name: "地点推荐", code: "recommend", description: "生成个性化 Top-K 候选地点", icon: Promotion },
  { name: "轨迹分析", code: "track", description: "读取并解析用户移动序列", icon: Connection },
  { name: "商业选址", code: "analyze_site_selection", description: "比较候选区域并生成空间证据", icon: MapLocation },
]

/** 打开数据集面板时关闭工具清单，保证同一时间只展开一个弹层。 */
const showDataset = () => {
  toolsOpen.value = false
}

/** 打开工具清单时关闭数据集面板。 */
const showTools = () => {
  datasetOpen.value = false
}
</script>

<template>
  <div class="workspace-controls">
    <el-popover
      v-model:visible="datasetOpen"
      placement="bottom-end"
      :width="316"
      trigger="click"
      :show-arrow="false"
      :show-after="0"
      :hide-after="0"
      popper-class="workspace-status-popper"
      @show="showDataset"
    >
      <template #reference>
        <button
          class="workspace-control"
          :class="{ 'is-open': datasetOpen }"
          type="button"
          aria-haspopup="dialog"
          :aria-expanded="datasetOpen"
        >
          <el-icon class="workspace-control__icon"><Coin /></el-icon>
          <span>东京数据集</span>
          <el-icon class="workspace-control__arrow"><ArrowDown /></el-icon>
        </button>
      </template>

      <section class="status-panel" aria-label="当前数据集">
        <header class="status-panel__header">
          <div>
            <span class="meta">当前数据环境</span>
            <strong>当前数据集</strong>
          </div>
          <span class="status-panel__live"><span class="dot"></span>已连接</span>
        </header>

        <div class="dataset-card">
          <span class="dataset-card__mark"><el-icon><MapLocation /></el-icon></span>
          <div>
            <strong>东京空间数据集</strong>
            <span class="meta">日本 · 东京都市圈</span>
          </div>
          <span class="state">当前</span>
        </div>

        <dl class="dataset-meta">
          <div><dt>数据内容</dt><dd>POI · 签到 · 用户轨迹</dd></div>
          <div><dt>分析引擎</dt><dd>PostGIS 空间引擎</dd></div>
          <div><dt>结果画布</dt><dd>Mapbox GL</dd></div>
        </dl>

        <router-link class="status-panel__action" to="/explore/poi" @click="datasetOpen = false">
          打开数据画布 <span>→</span>
        </router-link>
      </section>
    </el-popover>

    <el-popover
      v-model:visible="toolsOpen"
      placement="bottom-end"
      :width="344"
      trigger="click"
      :show-arrow="false"
      :show-after="0"
      :hide-after="0"
      popper-class="workspace-status-popper"
      @show="showTools"
    >
      <template #reference>
        <button
          class="workspace-control"
          :class="{ 'is-open': toolsOpen }"
          type="button"
          aria-haspopup="dialog"
          :aria-expanded="toolsOpen"
        >
          <el-icon class="workspace-control__icon"><Tools /></el-icon>
          <span>5 个工具就绪</span>
          <span class="workspace-control__signal" aria-hidden="true"></span>
        </button>
      </template>

      <section class="status-panel" aria-label="Agent 工具状态">
        <header class="status-panel__header">
          <div>
            <span class="meta">Agent 工具注册表</span>
            <strong>5 个空间工具已就绪</strong>
          </div>
          <span class="status-panel__live"><span class="dot"></span>已就绪</span>
        </header>

        <ul class="tool-list">
          <li v-for="item in toolItems" :key="item.code">
            <span class="tool-list__icon"><el-icon><component :is="item.icon" /></el-icon></span>
            <div>
              <strong>{{ item.name }}</strong>
              <span class="meta">{{ item.description }}</span>
              <code>{{ item.code }}</code>
            </div>
            <span class="state">可调用</span>
          </li>
        </ul>

        <router-link class="status-panel__action" to="/workspace" @click="toolsOpen = false">
          在 Agent 工作台中调用 <span>→</span>
        </router-link>
      </section>
    </el-popover>
  </div>
</template>

<style scoped>
.workspace-controls { display: flex; align-items: center; gap: 10px; }
.workspace-control { display: inline-flex; height: 38px; align-items: center; gap: 8px; padding: 0 12px; border: 1px solid var(--color-border); border-radius: 10px; color: #344054; background: #fff; box-shadow: 0 2px 6px rgba(55,73,117,.03); font-size: 12px; font-weight: 650; cursor: pointer; transition: border-color .18s ease, color .18s ease, background .18s ease, box-shadow .18s ease; }
.workspace-control:hover, .workspace-control.is-open { border-color: #aebfed; color: #3f5edc; background: #f8faff; box-shadow: 0 6px 16px rgba(67,88,158,.1); }
.workspace-control__icon { color: #64748b; font-size: 15px; }
.workspace-control.is-open .workspace-control__icon { color: #4967ed; }
.workspace-control__arrow { margin-left: 1px; font-size: 11px; transition: transform .18s ease; }
.workspace-control.is-open .workspace-control__arrow { transform: rotate(180deg); }
.workspace-control__signal { width: 7px; height: 7px; margin-left: 2px; border-radius: 50%; background: #2fc484; box-shadow: 0 0 0 4px rgba(47,196,132,.1); }

.status-panel { color: #344054; }
.status-panel__header { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; padding: 16px 16px 13px; border-bottom: 1px solid #edf1f6; }
.status-panel__header .meta, .status-panel__header strong { display: block; }
.status-panel__header .meta { margin-bottom: 4px; color: #7689bd; font-family: var(--font-mono); font-size: 8px; letter-spacing: .08em; }
.status-panel__header strong { color: #18243a; font-size: 14px; }
.status-panel__live { display: inline-flex; height: 24px; align-items: center; gap: 6px; padding: 0 8px; border-radius: 999px; color: #23825f; background: #eef9f5; font-size: 9px; font-weight: 700; }
.status-panel__live .dot { width: 6px; height: 6px; border-radius: 50%; background: #2fc484; box-shadow: 0 0 0 3px rgba(47,196,132,.12); }

.dataset-card { display: grid; grid-template-columns: 38px minmax(0,1fr) auto; align-items: center; gap: 10px; margin: 13px 14px 10px; padding: 11px; border: 1px solid #dce6f7; border-radius: 12px; background: linear-gradient(125deg,#f8faff,#f1f7ff); }
.dataset-card__mark { display: grid; width: 38px; height: 38px; place-items: center; border-radius: 11px; color: #fff; background: linear-gradient(145deg,#5375f0,#4861d9 58%,#26badd); box-shadow: 0 7px 14px rgba(69,91,205,.2); font-size: 18px; }
.dataset-card strong, .dataset-card .meta { display: block; }
.dataset-card strong { color: #273550; font-size: 11px; }
.dataset-card .meta { margin-top: 3px; color: #8190a6; font-size: 9px; }
.dataset-card .state { padding: 3px 7px; border-radius: 999px; color: #4965dd; background: #e8edff; font-size: 8px; font-style: normal; font-weight: 700; }
.dataset-meta { margin: 0; padding: 0 16px 11px; }
.dataset-meta > div { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 6px 0; }
.dataset-meta dt { color: #8b97a9; font-size: 9px; }
.dataset-meta dd { margin: 0; color: #526077; font-family: var(--font-mono); font-size: 8px; text-align: right; }

.tool-list { display: grid; gap: 0; margin: 0; padding: 7px 14px 10px; list-style: none; }
.tool-list li { display: grid; grid-template-columns: 34px minmax(0,1fr) auto; align-items: center; gap: 9px; padding: 9px 2px; border-bottom: 1px solid #eff2f6; }
.tool-list li:last-child { border-bottom: 0; }
.tool-list__icon { display: grid; width: 32px; height: 32px; place-items: center; border: 1px solid #dce6f5; border-radius: 10px; color: #4f6ae2; background: #f3f7ff; font-size: 15px; }
.tool-list strong, .tool-list .meta, .tool-list code { display: block; }
.tool-list strong { color: #2e3c54; font-size: 10px; }
.tool-list .meta { margin-top: 2px; color: #8b97a9; font-size: 8px; }
.tool-list code { margin-top: 3px; color: #7083b5; font-family: var(--font-mono); font-size: 7px; }
.tool-list .state { color: #2b956e; font-size: 8px; font-style: normal; font-weight: 700; }

.status-panel__action { display: flex; align-items: center; justify-content: space-between; padding: 11px 16px 12px; border-top: 1px solid #edf1f6; color: #4564df; background: #fbfcff; font-size: 10px; font-weight: 700; text-decoration: none; }
.status-panel__action:hover { color: #2f51dd; background: #f5f8ff; }
.status-panel__action span { font-size: 14px; transition: transform .18s ease; }
.status-panel__action:hover span { transform: translateX(2px); }

:global(.workspace-status-popper.el-popper) { overflow: hidden; padding: 0 !important; border: 1px solid #dbe4f0 !important; border-radius: 14px !important; box-shadow: 0 18px 46px rgba(39,54,91,.16) !important; }
</style>
