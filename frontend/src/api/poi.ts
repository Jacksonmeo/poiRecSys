import request from "./request"
import type { Poi } from "@/types"

interface PoiQuery {
  category?: string
  skip?: number
  limit?: number
}

/**
 * POI 数据接口。
 * input: category/skip/limit 查询参数。
 * output: POI 数组或类别数组。
 * 地图页面显式传入 limit，避免一次渲染过多实体导致浏览器卡死。
 */
/** 按类别和分页参数获取 POI 列表。 */
export const fetchPois = (query: PoiQuery = {}) =>
  request.get<never, Poi[]>("/pois", {
    params: {
      category: query.category || undefined,
      skip: query.skip,
      limit: query.limit,
    },
  })

/** 获取后端支持的 POI 类别，用于筛选器选项。 */
export const fetchPoiCategories = () => request.get<never, string[]>("/pois/categories")

/** 按 venue_id 获取单个 POI 的完整信息。 */
export const fetchPoiById = (poiId: string) => request.get<never, Poi>(`/pois/${poiId}`)
