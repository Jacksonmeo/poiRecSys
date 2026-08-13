"""POI Pydantic 模型：定义 API 响应数据结构。

第一阶段治理后移除全部旧 CSV 兼容字段（poi_id / name / category / lng / lat / address），
统一使用数据库原生字段：venue_id, display_name, venue_category, latitude, longitude。
"""

from pydantic import BaseModel, ConfigDict


class PoiResponse(BaseModel):
    """POI 响应结构，与 pois 表字段一一对应。

    from_attributes=True 允许直接从 ORM 对象构造 Pydantic 模型实例。
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    venue_id: str
    display_name: str | None = None
    venue_category_id: str | None = None
    venue_category: str | None = None
    latitude: float
    longitude: float
