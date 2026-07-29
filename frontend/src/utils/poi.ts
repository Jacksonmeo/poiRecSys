/** POI 展示名称工具函数。

所有 POI 相关的展示名称统一通过本模块获取，避免在多个组件中重复拼接逻辑。

同时兼容：
- 新数据库 POI（含 display_name / venue_id / venue_category）
- 旧 CSV POI（含 name / poi_id / category）
*/

export interface PoiLike {
  /** 数据库：Foursquare venue ID (新) */
  venue_id?: string
  /** 数据库预填充的展示名称 (新，最优先) */
  display_name?: string | null
  /** 数据库类别 (新) */
  venue_category?: string | null
  /** CSV 旧字段：POI 名称 */
  name?: string
  /** CSV 旧字段：POI ID */
  poi_id?: string
  /** CSV 旧字段：类别 */
  category?: string
}

/**
 * 从 Foursquare venue_id 或旧 CSV poi_id 提取短标识。
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
 * 2. 旧 CSV name
 * 3. 类别 + 短ID 组合
 * 4. 仅短ID（数据库）
 * 5. 仅类别
 * 6. 'POI'
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

  // 2. 旧 CSV name
  const name = poi.name?.trim()
  if (name) {
    return name
  }

  // 3. 类别（新或旧）+ 短ID
  const category = poi.venue_category?.trim() || poi.category?.trim() || ''
  const idSource = poi.venue_id || poi.poi_id || ''
  const shortId = getPoiShortId(idSource)

  if (category && shortId) {
    return `${category} · ${shortId}`
  }

  // 4. 仅短ID
  if (shortId) {
    return shortId
  }

  // 5. 仅类别
  if (category) {
    return category
  }

  // 6. 最终兜底
  return 'POI'
}

