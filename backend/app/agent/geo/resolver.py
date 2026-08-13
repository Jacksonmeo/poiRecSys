"""GeoResolver：地点名称 → 空间包围盒（bbox）（Stage 4 Step 4）。

LLM 只输出地点（如 涩谷 / Shibuya），坐标解析全部交给本模块；
未收录的地点返回 None，调用方回退默认东京中心区域。
未来替换真实地理编码服务时保持 resolve() 接口即可。
"""

from app.agent.prompts.prompt import DEFAULT_BBOX

# 内置地名词典：地点别名 → bbox（东京主要区域）
_PLACE_INDEX: dict[str, dict] = {
    "涩谷": {"min_lon": 139.695, "min_lat": 35.655, "max_lon": 139.715, "max_lat": 35.665},
    "shibuya": {"min_lon": 139.695, "min_lat": 35.655, "max_lon": 139.715, "max_lat": 35.665},
    "新宿": {"min_lon": 139.695, "min_lat": 35.685, "max_lon": 139.715, "max_lat": 35.705},
    "shinjuku": {"min_lon": 139.695, "min_lat": 35.685, "max_lon": 139.715, "max_lat": 35.705},
    "银座": {"min_lon": 139.750, "min_lat": 35.665, "max_lon": 139.775, "max_lat": 35.685},
    "ginza": {"min_lon": 139.750, "min_lat": 35.665, "max_lon": 139.775, "max_lat": 35.685},
    "浅草": {"min_lon": 139.785, "min_lat": 35.705, "max_lon": 139.805, "max_lat": 35.725},
    "asakusa": {"min_lon": 139.785, "min_lat": 35.705, "max_lon": 139.805, "max_lat": 35.725},
    "池袋": {"min_lon": 139.705, "min_lat": 35.725, "max_lon": 139.725, "max_lat": 35.745},
    "ikebukuro": {"min_lon": 139.705, "min_lat": 35.725, "max_lon": 139.725, "max_lat": 35.745},
}


class GeoResolver:
    """地点解析器：地点名 → bbox；未收录返回 None（回退默认区域）。"""

    def resolve(self, location: str) -> dict | None:
        """解析地点名称 → bbox 字典；未收录地点返回 None。"""
        key = (location or "").strip().lower()
        if not key:
            return None
        if key in ("东京", "tokyo", "东京中心", "tokyo center"):
            return dict(DEFAULT_BBOX)
        return dict(_PLACE_INDEX[key]) if key in _PLACE_INDEX else None


# 模块级单例：路由层与工具层直接复用
geo_resolver = GeoResolver()
