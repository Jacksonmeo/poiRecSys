"""QueryPOITool：查询 POI（按类别 / 空间范围 bbox）。

调用 poi_service（类别列表）与 spatial_service（bbox GeoJSON），
本文件不包含任何 SQL。
"""

from sqlalchemy.orm import Session

from app.agent.registry import AgentTool
from app.models.poi import Poi
from app.services.poi_service import get_pois
from app.services.spatial_service import get_pois_in_bbox


def _poi_summary(poi: Poi) -> dict:
    """POI ORM → 结构化结果（统一数据库字段，供地图图层直接使用）。"""
    return {
        "venue_id": poi.venue_id,
        "display_name": poi.display_name,
        "venue_category": poi.venue_category,
        "latitude": poi.latitude,
        "longitude": poi.longitude,
    }


class QueryPOITool(AgentTool):
    """按类别或空间范围（bbox）查询 POI 列表。"""

    name = "query_poi"
    description = "查询 POI（兴趣点）：支持按类别（如 Coffee Shop）或空间包围盒 bbox 过滤"
    parameters = {
        "type": "object",
        "properties": {
            "category": {"type": "string", "description": "POI 类别，如 Coffee Shop / Park"},
            "bbox": {
                "type": "object",
                "description": "空间包围盒 {min_lon, min_lat, max_lon, max_lat}",
                "properties": {
                    "min_lon": {"type": "number"},
                    "min_lat": {"type": "number"},
                    "max_lon": {"type": "number"},
                    "max_lat": {"type": "number"},
                },
            },
        },
    }

    def run(self, db: Session, args: dict) -> dict:
        """按类别或 bbox 查询 POI；有 bbox 走空间查询，否则按类别列表查询。"""
        args = self.validate(args)
        category = args.get("category")
        bbox = args.get("bbox")

        if bbox:
            # 空间范围查询 → GeoJSON FeatureCollection（spatial_service）
            collection = get_pois_in_bbox(db, **bbox, category=category)
            return {"type": "feature_collection", "data": collection.model_dump()}

        # 类别查询 → POI 列表（poi_service）
        pois = get_pois(db, category=category, limit=100)
        return {"type": "poi_list", "category": category, "data": [_poi_summary(p) for p in pois]}
