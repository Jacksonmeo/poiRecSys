"""空间分析接口的 Pydantic 模型（Stage 2 PostGIS）。

包含：
- GeoJSON FeatureCollection（bbox 查询返回格式，符合 RFC 7946 子集）
- NearbyPoi（半径查询结果）
- DensityCellResponse（格网密度结果）
"""

from typing import Literal

from pydantic import BaseModel


class GeoPoint(BaseModel):
    """GeoJSON 点几何。coordinates 为 [longitude, latitude]（WGS84）。"""

    type: Literal["Point"] = "Point"
    coordinates: tuple[float, float]


class PoiFeatureProperties(BaseModel):
    """GeoJSON feature 属性：与 pois 表字段一一对应。"""

    venue_id: str
    category: str | None = None
    name: str | None = None


class PoiFeature(BaseModel):
    """单个 POI 的 GeoJSON feature。"""

    type: Literal["Feature"] = "Feature"
    geometry: GeoPoint
    properties: PoiFeatureProperties


class FeatureCollection(BaseModel):
    """空间查询的统一 GeoJSON 响应结构。"""

    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[PoiFeature]


class NearbyPoi(BaseModel):
    """半径查询结果：POI 基本信息 + 距查询中心点的距离（米）。"""

    venue_id: str
    display_name: str | None = None
    venue_category: str | None = None
    latitude: float
    longitude: float
    distance_m: float


class DensityCellResponse(BaseModel):
    """密度格网单元：格点中心坐标 + 格内 POI 数量（供 Mapbox heatmap 使用）。"""

    lat: float
    lon: float
    count: int
