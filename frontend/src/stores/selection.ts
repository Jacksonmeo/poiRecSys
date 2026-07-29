/**
 * Pinia 全局选择状态管理。
 *
 * 用于跨页面共享当前选中的用户 ID 和会话 ID，
 * 使得轨迹页和推荐页之间可以保持一致的选中状态，
 * 避免各页面各自维护重复的筛选状态。
 */
import { defineStore } from "pinia"
import { ref } from "vue"

/**
 * 使用 Composition API 风格定义 store。
 * 存储当前选中的用户与 session 标识，
 * 供轨迹页和推荐页在切换页面时复用。
 */
export const useSelectionStore = defineStore("selection", () => {
  // 当前选中的用户 ID，由轨迹页或推荐页写入。
  const selectedUserId = ref("")
  // 当前选中的 session ID，与 selectedUserId 绑定。
  const selectedSessionId = ref("")

  /**
   * 统一设置选中的用户和会话。
   * 作为唯一的修改入口，确保状态变更可追踪。
   */
  const setSelection = (userId: string, sessionId: string) => {
    selectedUserId.value = userId
    selectedSessionId.value = sessionId
  }

  return { selectedUserId, selectedSessionId, setSelection }
})
