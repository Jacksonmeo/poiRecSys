"""POI 接口测试：列表分页、类别筛选、详情与统一响应格式。"""

from tests.conftest import client


def test_list_pois_unified_envelope(seeded):
    """验证统一响应格式：{code, message, data}。"""
    resp = client.get("/api/pois", params={"limit": 10})
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["message"] == "success"
    assert isinstance(body["data"], list)
    assert len(body["data"]) == 4


def test_list_pois_no_legacy_fields(seeded):
    """验证旧 CSV 兼容字段已移除：无 poi_id/name/category/lng/lat/address。"""
    resp = client.get("/api/pois", params={"limit": 10})
    poi = resp.json()["data"][0]
    assert "venue_id" in poi
    assert "longitude" in poi and "latitude" in poi
    for legacy in ("poi_id", "name", "category", "lng", "lat", "address"):
        assert legacy not in poi, f"旧字段 {legacy} 不应出现在响应中"


def test_list_pois_pagination(seeded):
    """分页：limit=2 只返回 2 条。"""
    resp = client.get("/api/pois", params={"limit": 2})
    assert resp.status_code == 200
    assert len(resp.json()["data"]) == 2


def test_list_pois_category_filter(seeded):
    """按类别精确筛选。"""
    resp = client.get("/api/pois", params={"category": "Park"})
    data = resp.json()["data"]
    assert len(data) == 1
    assert data[0]["venue_category"] == "Park"
    assert data[0]["venue_id"] == "poi_park"


def test_list_categories(seeded):
    """类别接口返回去重列表。"""
    resp = client.get("/api/pois/categories")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert "Park" in body["data"]
    assert "Coffee Shop" in body["data"]


def test_get_poi_detail(seeded):
    """详情接口返回单条 POI。"""
    resp = client.get("/api/pois/poi_coffee")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["venue_id"] == "poi_coffee"
    assert data["display_name"] == "Central Coffee"


def test_get_poi_not_found_404(seeded):
    """不存在的 POI 返回统一 404 格式。"""
    resp = client.get("/api/pois/not-exist")
    assert resp.status_code == 404
    body = resp.json()
    assert body["code"] == 404
    assert body["data"] is None
    assert "not found" in body["message"]


def test_validation_error_unified_422():
    """参数校验失败返回统一 422 格式。"""
    resp = client.get("/api/pois", params={"limit": 999999})
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == 422
    assert body["data"] is None
