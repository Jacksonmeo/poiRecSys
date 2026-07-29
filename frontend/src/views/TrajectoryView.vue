<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue"
import { ElMessage } from "element-plus"
import { getSessionTrajectory, getUserSessions, getUsers } from "@/api/trajectory"
import MapContainer from "@/components/map/MapContainer.vue"
import type { SessionSummary, SessionTrajectoryResponse, UserSummary } from "@/types"

const mapRef = ref<InstanceType<typeof MapContainer>>()
const users = ref<UserSummary[]>([])
const sessions = ref<SessionSummary[]>([])
const selectedUserId = ref("")
const selectedSessionId = ref("")
const trajectory = ref<SessionTrajectoryResponse>()
const usersLoading = ref(false)
const sessionsLoading = ref(false)
const trajectoryLoading = ref(false)
const errorMessage = ref("")

let searchTimer: ReturnType<typeof setTimeout> | undefined
let userRequestVersion = 0
let sessionRequestVersion = 0
let trajectoryRequestVersion = 0

const sortedPoints = computed(() =>
  [...(trajectory.value?.points || [])].sort((a, b) => a.sequence_no - b.sequence_no),
)

const formatTime = (value?: string) => {
  if (!value) return "-"
  return new Date(value).toLocaleString()
}

const sessionLabel = (session: SessionSummary) =>
  `${formatTime(session.start_time)} - ${formatTime(session.end_time)} · ${session.checkin_count} check-ins`

/**
 * 清空轨迹状态与地图轨迹层。
 * input: 无。
 * output: 当前轨迹数据置空，并移除 Mapbox trajectory layer。
 * 这样切换用户/session 时不会显示上一条轨迹的残留。
 */
const resetTrajectory = () => {
  trajectory.value = undefined
  mapRef.value?.clearTrajectoryLayer()
}

/**
 * 远程搜索用户。
 * input: keyword 为用户输入的搜索关键字。
 * output: users 选择器数据。
 * 使用 300ms 防抖和请求版本号，避免快速输入造成旧响应覆盖新结果。
 */
const searchUsers = (keyword = "") => {
  if (searchTimer) window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(async () => {
    const currentVersion = ++userRequestVersion
    usersLoading.value = true
    errorMessage.value = ""

    try {
      const result = await getUsers({ keyword: keyword.trim() || undefined, skip: 0, limit: 20 })
      if (currentVersion !== userRequestVersion) return
      users.value = result.items
      if (!selectedUserId.value && users.value.length) selectedUserId.value = users.value[0].user_id
    } catch {
      if (currentVersion !== userRequestVersion) return
      users.value = []
      errorMessage.value = "用户列表加载失败，请确认后端服务已启动。"
      ElMessage.error(errorMessage.value)
    } finally {
      if (currentVersion === userRequestVersion) usersLoading.value = false
    }
  }, 300)
}

const loadSessions = async (userId: string) => {
  const currentVersion = ++sessionRequestVersion
  sessionsLoading.value = true
  errorMessage.value = ""
  sessions.value = []
  selectedSessionId.value = ""
  resetTrajectory()

  if (!userId) {
    sessionsLoading.value = false
    return
  }

  try {
    const result = await getUserSessions(userId, { skip: 0, limit: 100 })
    if (currentVersion !== sessionRequestVersion) return
    sessions.value = result.items
    selectedSessionId.value = sessions.value[0]?.session_id || ""
  } catch {
    if (currentVersion !== sessionRequestVersion) return
    errorMessage.value = "Session 列表加载失败。"
    ElMessage.error(errorMessage.value)
  } finally {
    if (currentVersion === sessionRequestVersion) sessionsLoading.value = false
  }
}

const loadTrajectory = async (sessionId: string) => {
  const currentVersion = ++trajectoryRequestVersion
  trajectoryLoading.value = true
  errorMessage.value = ""
  resetTrajectory()

  if (!sessionId) {
    trajectoryLoading.value = false
    return
  }

  try {
    const result = await getSessionTrajectory(sessionId)
    if (currentVersion !== trajectoryRequestVersion || selectedSessionId.value !== sessionId) return
    trajectory.value = result
    await nextTick()
    mapRef.value?.addTrajectoryLayer(result.points, { sessionId: result.session.session_id })
  } catch {
    if (currentVersion !== trajectoryRequestVersion) return
    errorMessage.value = "轨迹详情加载失败。"
    ElMessage.error(errorMessage.value)
  } finally {
    if (currentVersion === trajectoryRequestVersion) trajectoryLoading.value = false
  }
}

watch(selectedUserId, (userId) => {
  void loadSessions(userId)
})

watch(selectedSessionId, (sessionId) => {
  void loadTrajectory(sessionId)
})

onMounted(() => searchUsers(""))

onBeforeUnmount(() => {
  userRequestVersion += 1
  sessionRequestVersion += 1
  trajectoryRequestVersion += 1
  if (searchTimer) window.clearTimeout(searchTimer)
  mapRef.value?.clearTrajectoryLayer()
})
</script>

<template>
  <section class="trajectory-page">
    <div class="page-toolbar">
      <h2>用户轨迹</h2>
      <div class="filters">
        <el-select
          v-model="selectedUserId"
          filterable
          remote
          clearable
          :remote-method="searchUsers"
          :loading="usersLoading"
          placeholder="搜索或选择用户"
        >
          <el-option v-for="user in users" :key="user.user_id" :label="user.user_id" :value="user.user_id" />
        </el-select>
        <el-select
          v-model="selectedSessionId"
          clearable
          filterable
          :disabled="!selectedUserId"
          :loading="sessionsLoading"
          placeholder="搜索或选择 session"
        >
          <el-option
            v-for="session in sessions"
            :key="session.session_id"
            :label="sessionLabel(session)"
            :value="session.session_id"
          />
        </el-select>
      </div>
    </div>

    <el-alert v-if="errorMessage" class="page-alert" type="error" :title="errorMessage" show-icon />

    <el-row :gutter="16" class="content-row">
      <el-col :xs="24" :lg="17" class="map-column">
        <el-card v-loading="trajectoryLoading" shadow="never" class="map-card">
          <MapContainer ref="mapRef" />
        </el-card>
      </el-col>
      <el-col :xs="24" :lg="7" class="side-column">
        <el-card shadow="never" class="timeline-card">
          <template #header>
            <div class="timeline-header">
              <span>轨迹点</span>
              <span v-if="trajectory?.session">{{ trajectory.session.checkin_count }}</span>
            </div>
          </template>

          <el-empty v-if="!trajectoryLoading && !sortedPoints.length" description="暂无轨迹数据" />
          <el-timeline v-else>
            <el-timeline-item
              v-for="point in sortedPoints"
              :key="`${point.venue_id}-${point.sequence_no}`"
              :timestamp="formatTime(point.utc_timestamp)"
            >
              <div class="point-row">
                <strong>{{ point.sequence_no }}. {{ point.display_name || point.venue_id }}</strong>
                <span>{{ point.venue_category || "未知类别" }}</span>
                <small>{{ point.longitude.toFixed(6) }}, {{ point.latitude.toFixed(6) }}</small>
              </div>
            </el-timeline-item>
          </el-timeline>
        </el-card>
      </el-col>
    </el-row>
  </section>
</template>

<style scoped>
.trajectory-page {
  display: grid;
  height: 100%;
  min-height: 0;
  grid-template-rows: auto auto minmax(0, 1fr);
  gap: var(--space-3);
}

.page-toolbar,
.filters,
.timeline-header {
  display: flex;
  align-items: center;
}

.page-toolbar {
  justify-content: space-between;
  height: 48px;
}

.filters {
  gap: var(--space-3);
}

.filters .el-select {
  width: 280px;
}

h2 {
  margin: 0;
  font-size: 20px;
}

.page-alert {
  margin: 0;
}

.content-row,
.map-column,
.map-card,
.side-column,
.timeline-card {
  height: 100%;
  min-height: 0;
}

.map-card :deep(.el-card__body),
.timeline-card :deep(.el-card__body) {
  height: 100%;
}

.map-card :deep(.el-card__body) {
  padding: var(--space-2);
}

.timeline-card {
  overflow: hidden;
}

.timeline-card :deep(.el-card__body) {
  overflow: auto;
}

.timeline-header {
  justify-content: space-between;
}

.point-row {
  display: grid;
  gap: var(--space-1);
  line-height: 1.35;
}

.point-row span,
.point-row small {
  color: var(--color-text-secondary);
}
</style>
