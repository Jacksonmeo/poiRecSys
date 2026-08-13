/** POI 展示名称工具函数。

所有 POI 相关的展示名称统一通过本模块获取，避免在多个组件中重复拼接逻辑。

第一阶段治理后仅依赖数据库字段（venue_id / display_name / venue_category），
旧 CSV 字段（name / poi_id / category）已移除。
*/

export interface PoiLike {
  /** Foursquare venue ID */
  venue_id?: string
  /** 数据库预填充的展示名称（最优先） */
  display_name?: string | null
  /** 数据库类别 */
  venue_category?: string | null
}

/**
 * 从 Foursquare venue_id 提取短标识。
 */
export function getPoiShortId(
  venueId?: string,
  length = 6,
): string {
  if (!venueId) {
    return ''
  }

  return venueId.length <= length
    ? venueId
    : venueId.slice(-length)
}

/**
 * 获取 POI 的最佳展示名称。
 *
 * 优先级：
 * 1. 数据库 display_name（最优先）
 * 2. 类别 + 短ID 组合
 * 3. 仅短ID
 * 4. 仅类别
 * 5. 'POI'
 *
 * 此函数不修改原始 ID，只返回展示用字符串。
 */
export function getPoiDisplayName(
  poi: PoiLike,
): string {
  // 1. 数据库 display_name（最优先）
  const displayName = poi.display_name?.trim()
  if (displayName) {
    return displayName
  }

  // 2. 类别 + 短ID
  const category = poi.venue_category?.trim() || ''
  const shortId = getPoiShortId(poi.venue_id)

  if (category && shortId) {
    return `${category} · ${shortId}`
  }

  // 3. 仅短ID
  if (shortId) {
    return shortId
  }

  // 4. 仅类别
  if (category) {
    return category
  }

  // 5. 最终兜底
  return 'POI'
}
