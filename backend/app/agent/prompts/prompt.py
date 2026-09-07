"""Agent 提示词与意图规则路由（Stage 3 规则路由 + Stage 4 降级兜底）。

Stage 4 接入 LLM Function Calling 后，本文件的规则路由（_route_intent）作为
LLM 不可用/输出非法时的降级路径；SYSTEM_PROMPT 作为 LLM 系统提示词，
各工具的 parameters（JSON Schema，见 tools/*.py）直接作为函数声明。
"""

from dataclasses import dataclass, field

# 默认分析区域：东京中心（消息中无位置信息时的兜底 bbox）
DEFAULT_BBOX = {"min_lon": 139.69, "min_lat": 35.64, "max_lon": 139.81, "max_lat": 35.72}

# 类别关键词 → venue_category（优先级最高：具体实体优先于一般意图）
CATEGORY_KEYWORDS: dict[str, str] = {
    "咖啡店": "Coffee Shop",
    "咖啡厅": "Coffee Shop",
    "咖啡": "Coffee Shop",
    "医院": "Medical Center",
    "医疗中心": "Medical Center",
    "诊所": "Medical Center",
    "hospital": "Medical Center",
    "medical center": "Medical Center",
    "拉面": "Ramen / Noodle House",
    "面馆": "Ramen / Noodle House",
    "公园": "Park",
    "购物": "Shopping Mall",
    "商场": "Shopping Mall",
    "餐厅": "Restaurant",
    "酒吧": "Bar",
    "酒馆": "Bar",
    "bar": "Bar",
    "运动场": "Athletic & Sport",
    "体育场": "Stadium",
    "运动": "Athletic & Sport",
    "体育": "Athletic & Sport",
    "athletic & sport": "Athletic & Sport",
    "stadium": "Stadium",
    "健身房": "Gym / Fitness Center",
    "健身": "Gym / Fitness Center",
    "gym": "Gym / Fitness Center",
}

# 意图关键词 → 工具名
INTENT_KEYWORDS: dict[str, str] = {
    "密度": "spatial_density",
    "热力": "spatial_density",
    "空间分布": "spatial_density",
    "分布": "spatial_density",
    "推荐": "recommend",
    "top-k": "recommend",
    "轨迹": "track",
    "签到": "track",
    "历史": "track",
}

SITE_SELECTION_AREA_ALIASES: dict[str, str] = {
    "shinjuku": "shinjuku",
    "新宿": "shinjuku",
    "shibuya": "shibuya",
    "涩谷": "shibuya",
    "渋谷": "shibuya",
    "ginza": "ginza",
    "银座": "ginza",
    "銀座": "ginza",
    "ikebukuro": "ikebukuro",
    "池袋": "ikebukuro",
}
SITE_SELECTION_DEFAULT_AREAS = ["shinjuku", "shibuya", "ginza", "ikebukuro"]

# 意图 → 回复模板（{字段} 由 service 填充）
REPLY_TEMPLATES: dict[str, str] = {
    "query_poi": "共找到 {count} 个 POI{scope}：{names}。地图已标注点位。",
    "spatial_density": "共统计 {count} 个 POI 的空间密度，生成 {cells} 个格网密度点，地图已渲染热力图。",
    "recommend": "为您推荐 Top-{top_k} POI（会话 {session_id}）：{names}。",
    "track": "会话 {session_id} 共 {count} 个轨迹点：{names}。地图已绘制轨迹。",
    "analyze_site_selection": "已完成候选区域的选址事实分析。",
    "fallback": "我可以帮您：查 POI（如「找咖啡店」「找医院」「找酒吧」「找运动场」「附近有什么」）、空间密度分析（如「空间密度」）、"
    "推荐查询（如「给我推荐」）、轨迹查询（如「查看轨迹」）。",
}

# 预留：未来 LLM 接入时的系统提示词
SYSTEM_PROMPT = (
    "你是 GeoAgent，一个空间数据分析助手。你能够使用以下工具："
    "query_poi（查询 POI，支持类别与空间范围，类别如 Coffee Shop / Medical Center / Bar / Athletic & Sport）、spatial_density（格网密度分析，"
    "输出热力图数据）、recommend（返回模型 Top-K 推荐 POI）、track（查询会话轨迹）。"
    "analyze_site_selection 可分析新宿、涩谷、银座、池袋候选区的空间指标、"
    "用户行为指标和区域流向，并返回结构化 SiteSelection Artifact。"
    "根据用户意图选择合适的工具，工具调用结束后用中文简洁总结结果。"
)


@dataclass(frozen=True)
class Intent:
    """意图识别结果：目标工具名 + 工具参数 + 可选文本回复。

    text 为 LLM 直接回复（无工具调用）时携带；规则路由时为默认空字符串。
    """

    tool: str
    args: dict
    text: str = ""
    context: dict = field(default_factory=dict)


# 密度分析意图的默认参数（无位置信息时用东京中心）
_DENSITY_DEFAULT_ARGS = {"bbox": DEFAULT_BBOX, "grid_size": 10}


def _route_intent(message: str) -> Intent:
    """规则路由：类别关键词 > 意图关键词 > 附近 > 兜底（LLM 降级路径）。

    类别关键词命中时直接带出 venue_category；「附近」给默认东京中心 bbox。
    """
    msg = message.lower().strip()

    if "选址" in msg or "候选区域" in msg or "site selection" in msg:
        positioned_areas = []
        for alias, area_id in SITE_SELECTION_AREA_ALIASES.items():
            position = msg.find(alias)
            if position >= 0:
                positioned_areas.append((position, area_id))
        matched = []
        for _, area_id in sorted(positioned_areas):
            if area_id not in matched:
                matched.append(area_id)
        return Intent(
            tool="analyze_site_selection",
            args={"area_ids": matched or list(SITE_SELECTION_DEFAULT_AREAS)},
        )

    for keyword, category in CATEGORY_KEYWORDS.items():
        if keyword in msg:
            args: dict = {"category": category}
            if "附近" in msg:
                args["bbox"] = DEFAULT_BBOX
            return Intent(tool="query_poi", args=args)

    for keyword, tool in INTENT_KEYWORDS.items():
        if keyword in msg:
            if tool == "spatial_density":
                return Intent(tool=tool, args=dict(_DENSITY_DEFAULT_ARGS))
            return Intent(tool=tool, args={})

    if "附近" in msg:
        return Intent(tool="query_poi", args={"bbox": DEFAULT_BBOX})

    return Intent(tool="", args={})
