/**
 * Axios 请求实例与全局配置。
 *
 * 职责：
 * - 创建统一的 Axios 实例，配置 baseURL 和超时时间
 * - 通过环境变量 VITE_API_BASE_URL 切换后端地址
 * - 响应拦截器自动解包 { data } 包装，简化调用方代码
 */
import axios from "axios"

// 创建 Axios 实例，后端地址可通过环境变量覆盖。
const request = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000/api",
  timeout: 10000,
})

/**
 * 响应拦截器。
 * 后端统一返回 { data: ... } 格式，拦截器自动提取 data 字段，
 * 使得各 API 函数的返回类型直接指向业务数据，无需手动 .data。
 */
request.interceptors.response.use(
  (response) => {
    const payload = response.data
    // 如果响应体是包含 data 属性的对象，则解包 data。
    if (payload && typeof payload === "object" && "data" in payload) {
      return payload.data
    }
    return payload
  },
  // 请求失败时直接抛出错误，由调用方处理。
  (error) => Promise.reject(error),
)

export default request
