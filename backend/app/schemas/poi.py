"""POI Pydantic 模型：定义 API 请求/响应数据结构。

主字段使用数据库原生列名（venue_id, venue_category, latitude, longitude）。
同时通过 computed_field 提供旧前端兼容字段（poi_id, name, category, lng, lat, address），
确保迁移后现有 Vue3/Cesium 页面仍可正常使用。
"""

from pydantic import BaseModel, ConfigDict, computed_field


class PoiResponse(BaseModel):
    """POI 列表/详情接口的统一响应结构。

    字段分为两组：
    1. 数据库原生字段：id, venue_id, venue_category_id, venue_category, latitude, longitude
    2. 旧前端兼容字段（computed）：poi_id, name, category, lng, lat, address

    from_attributes=True 允许直接从 ORM 对象构造 Pydantic 模型实例。
    """

    model_config = ConfigDict(from_attributes=True)

    # ── 数据库原生字段 ──────────────────────────────────────────
    id: int
    venue_id: str
    display_name: str | None = None
    venue_category_id: str | None = None
    venue_category: str | None = None
    latitude: float
    longitude: float

    # ── 旧前端兼容字段（computed_field） ──────────────────────────

    @computed_field
    @property
    def poi_id(self) -> str:
        """兼容字段：映射自 venue_id，保持旧前端 poi_id 引用有效。"""
        return self.venue_id

    @computed_field
    @property
    def name(self) -> str:
        """兼容字段：优先使用 display_name，为空时兜底为 venue_id 后6位。

        数据库新增 display_name 列后，此字段自动反映真实 POI 名称，
        不再返回完整长 ID。
        """
        if self.display_name:
            return self.display_name
        if self.venue_category:
            return f"{self.venue_category} · {self.venue_id[-6:]}"
        return self.venue_id[-6:]

    @computed_field
    @property
    def category(self) -> str:
        """兼容字段：映射自 venue_category，空值时返回空字符串。"""
        return self.venue_category or ""

    @computed_field
    @property
    def lng(self) -> float:
        """兼容字段：映射自 longitude，保持旧前端 lng 字段名可用。"""
        return self.longitude

    @computed_field
    @property
    def lat(self) -> float:
        """兼容字段：映射自 latitude，保持旧前端 lat 字段名可用。"""
        return self.latitude

    @computed_field
    @property
    def address(self) -> str:
        """兼容字段：数据库无 address 列，返回空字符串占位。"""
        return ""


class PoiListResponse(BaseModel):
    """POI 列表响应包装器，保持与旧 API 的 { data: [...] } 格式兼容。"""

    data: list[PoiResponse]


class PoiDetailResponse(BaseModel):
    """POI 详情响应包装器，单条 POI 的 { data: {...} } 格式。"""

    data: PoiResponse


class CategoryListResponse(BaseModel):
    """POI 类别列表响应包装器，返回所有不重复类别名称的字符串数组。"""

    data: list[str]
