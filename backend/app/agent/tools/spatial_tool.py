"""SpatialAnalysisTool：空间密度分析（格网统计 → heatmap 数据）。

调用 spatial_service.get_density_grid，本文件不包含任何 SQL。
"""

from sqlalchemy.orm import Session

from app.agent.registry import AgentTool
from app.services.spatial_service import get_density_grid


class SpatialAnalysisTool(AgentTool):
    """把 bbox 切成 N×N 格网统计 POI 数量，输出 Mapbox heatmap 数据。"""

    name = "spatial_density"
    description = "空间密度分析：统计指定区域（bbox）内 POI 的格网密度，输出热力图数据"
    parameters = {
        "type": "object",
        "properties": {
            "bbox": {
                "type": "object",
                "description": "分析区域 {min_lon, min_lat, max_lon, max_lat}",
                "properties": {
                    "min_lon": {"type": "number"},
                    "min_lat": {"type": "number"},
                    "max_lon": {"type": "number"},
                    "max_lat": {"type": "number"},
                },
            },
            "grid_size": {"type": "integer", "description": "单边格网数（2-100）", "default": 10},
        },
        "required": ["bbox"],
    }

    def run(self, db: Session, args: dict) -> dict:
        """按 bbox 切格网统计密度，输出热力图格网数据。"""
        args = self.validate(args)
        bbox = args["bbox"]
        grid_size = args.get("grid_size", 10)

        cells = get_density_grid(db, **bbox, grid_size=grid_size)
        total = sum(cell.count for cell in cells)
        return {
            "type": "density",
            "cells": [cell.model_dump() for cell in cells],
            "count": total,
            "grid_size": grid_size,
        }
