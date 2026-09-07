/**
 * 聊天面板拖拽调宽（Stage 5.5 Workspace）。
 * 约定：默认 420px，最小 360px，最大 520px。
 * 返回面板宽度 ref 与分隔条拖拽事件（pointerdown 驱动全局 move/up）。
 */
import { ref } from "vue"

export const PANEL_WIDTH_DEFAULT = 456
export const PANEL_WIDTH_MIN = 390
export const PANEL_WIDTH_MAX = 540

/** 提供 Agent 面板的拖拽调宽状态和事件处理器。 */
export const usePanelResize = () => {
  const panelWidth = ref(PANEL_WIDTH_DEFAULT)
  const dragging = ref(false)

  /** 分隔条 pointerdown：记录起点，注册全局 move/up，拖拽中禁用文本选择。 */
  const startResize = (event: PointerEvent) => {
    event.preventDefault()
    dragging.value = true
    document.body.style.userSelect = "none"
    const startX = event.clientX
    const startWidth = panelWidth.value

    /** 根据指针横向位移计算新的面板宽度，并限制在安全范围内。 */
    const move = (moveEvent: PointerEvent) => {
      const next = startWidth + (moveEvent.clientX - startX)
      panelWidth.value = Math.min(PANEL_WIDTH_MAX, Math.max(PANEL_WIDTH_MIN, next))
    }
    /** 结束拖拽并清理全局监听器。 */
    const stop = () => {
      dragging.value = false
      document.body.style.userSelect = ""
      window.removeEventListener("pointermove", move)
      window.removeEventListener("pointerup", stop)
    }
    window.addEventListener("pointermove", move)
    window.addEventListener("pointerup", stop)
  }

  return { panelWidth, dragging, startResize }
}
