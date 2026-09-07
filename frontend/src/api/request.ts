/**
 * Axios 请求实例与全局配置。
 *
 * 职责：
 * - 创建统一的 Axios 实例，配置 baseURL 和超时时间
 * - 通过环境变量 VITE_API_BASE_URL 切换后端地址
 * - 响应拦截器处理统一响应格式 { code, message, data }，自动解包 data
 * - 错误拦截器统一弹出错误提示（ElMessage），页面无需重复处理
 *
 * 统一响应约定（与后端 main.py 全局异常处理器配套）：
 *   成功: { code: 0, message: "success", data: {...} }
 *   失败: { code: <HTTP状态码>, message: "<错误描述>", data: null }
 */
import axios from "axios"
import { ElMessage } from "element-plus"

// 创建 Axios 实例，后端地址可通过环境变量覆盖。
const request = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000/api",
  timeout: 10000,
})

/**
 * 响应拦截器。
 * 后端统一返回 { code, message, data }，code === 0 时自动解包 data，
 * 使各 API 函数的返回类型直接指向业务数据；code !== 0 时按错误处理。
 */
request.interceptors.response.use(
  (response) => {
    const payload = response.data
    if (payload && typeof payload === "object" && "code" in payload) {
      if (payload.code === 0) {
        return payload.data
      }
      // 业务码非 0：视为请求失败（后端错误场景均通过 HTTP 状态码 + 全局异常处理器返回）
      return Promise.reject(new Error(payload.message || "请求失败"))
    }
    return payload
  },
  // HTTP 错误：统一读取后端 message 并弹出提示，页面只需 catch 后处理局部状态。
  (error) => {
    const message = error.response?.data?.message || "网络异常，请稍后重试。"
    ElMessage.error(message)
    return Promise.reject(new Error(message))
  },
)

export default request
