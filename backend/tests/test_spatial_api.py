"""Stage 2 空间接口测试：bbox 查询 / 半径查询 / 格网密度 / GeoJSON 格式。

seeded fixture 提供的 4 个 POI（WGS84）：
    poi_coffee (139.700, 35.680)  poi_ramen (139.710, 35.690)
    poi_park   (139.720, 35.670)  poi_mall  (139.730, 35.700)
"""

from tests.conftest import client

# 覆盖全部 4 个 POI 的包围盒
FULL_BBOX = {
    "min_lon": 139.69,
    "min_lat": 35.66,
    "max_lon": 139.74,
    "max_lat": 35.71,
}

# 只覆盖 poi_coffee 的小包围盒
COFFEE_BBOX = {
    "min_lon": 139.695,
    "min_lat": 35.675,
    "max_lon": 139.705,
    "max_lat": 35.685,
}


# ── bbox 空间查询（/api/pois/spatial）─────────────────────────────


def test_spatial_bbox_returns_all_pois(seeded):
    """大包围盒应返回全部 4 个 POI。"""
    resp = client.get("/api/pois/spatial", params=FULL_BBOX)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) == 4
    venue_ids = {f["properties"]["venue_id"] for f in data["features"]}
    assert venue_ids == {"poi_coffee", "poi_ramen", "poi_park", "poi_mall"}


def test_spatial_bbox_filters_by_range(seeded):
    """小包围盒只返回落在其中的 POI。"""
    resp = client.get("/api/pois/spatial", params=COFFEE_BBOX)
    features = resp.json()["data"]["features"]
    assert len(features) == 1
    assert features[0]["properties"]["venue_id"] == "poi_coffee"


def test_spatial_bbox_category_filter(seeded):
    """bbox + category 组合筛选。"""
    params = {**FULL_BBOX, "category": "Park"}
    resp = client.get("/api/pois/spatial", params=params)
    features = resp.json()["data"]["features"]
    assert len(features) == 1
    assert features[0]["properties"]["venue_id"] == "poi_park"


def test_spatial_geojson_format(seeded):
    """GeoJSON 格式正确性：type/geometry.coordinates/properties 符合规范。"""
    resp = client.get("/api/pois/spatial", params=FULL_BBOX)
    data = resp.json()["data"]

    assert data["type"] == "FeatureCollection"
    assert isinstance(data["features"], list)

    feature = next(f for f in data["features"] if f["properties"]["venue_id"] == "poi_coffee")
    assert feature["type"] == "Feature"
    assert feature["geometry"]["type"] == "Point"
    # coordinates 顺序必须是 [longitude, latitude]
    lon, lat = feature["geometry"]["coordinates"]
    assert lon == 139.700
    assert lat == 35.680
    # properties 包含 venue_id / category / name
    props = feature["properties"]
    assert props["venue_id"] == "poi_coffee"
    assert props["category"] == "Coffee Shop"
    assert props["name"] == "Central Coffee"


def test_spatial_invalid_bbox_422(seeded):
    """min > max 的包围盒返回统一 422 格式。"""
    params = {"min_lon": 139.74, "min_lat": 35.71, "max_lon": 139.69, "max_lat": 35.66}
    resp = client.get("/api/pois/spatial", params=params)
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == 422
    assert body["data"] is None


def test_spatial_missing_params_422():
    """缺少必填 bbox 参数返回统一 422 格式。"""
    resp = client.get("/api/pois/spatial")
    assert resp.status_code == 422
    assert resp.json()["code"] == 422


# ── 半径查询（/api/pois/nearby）────────────────────────────────────


def test_nearby_small_radius_only_self(seeded):
    """500 米半径内只有查询中心点自身。"""
    resp = client.get("/api/pois/nearby", params={"longitude": 139.700, "latitude": 35.680, "radius_meter": 500})
    data = resp.json()["data"]
    assert [poi["venue_id"] for poi in data] == ["poi_coffee"]
    assert data[0]["distance_m"] < 100  # 自身距离近似为 0


def test_nearby_radius_orders_by_distance(seeded):
    """3000 米半径返回 3 个 POI，按距离升序且都在半径内。"""
    resp = client.get("/api/pois/nearby", params={"longitude": 139.700, "latitude": 35.680, "radius_meter": 3000})
    data = resp.json()["data"]
    assert len(data) == 3
    distances = [poi["distance_m"] for poi in data]
    assert distances == sorted(distances)
    assert all(d < 3000 for d in distances)


def test_nearby_category_filter(seeded):
    """半径查询 + category 组合筛选。"""
    params = {"longitude": 139.700, "latitude": 35.680, "radius_meter": 5000, "category": "Park"}
    resp = client.get("/api/pois/nearby", params=params)
    data = resp.json()["data"]
    assert len(data) == 1
    assert data[0]["venue_id"] == "poi_park"


def test_nearby_invalid_radius_422(seeded):
    """radius_meter 必须为正数，否则统一 422。"""
    resp = client.get("/api/pois/nearby", params={"longitude": 139.700, "latitude": 35.680, "radius_meter": 0})
    assert resp.status_code == 422
    assert resp.json()["code"] == 422


# ── 密度分析（/api/analysis/density）──────────────────────────────


def test_density_grid_counts_all_pois(seeded):
    """5×5 格网：4 个 POI 各占一格，总数守恒。"""
    resp = client.get("/api/analysis/density", params={**FULL_BBOX, "grid_size": 5})
    assert resp.status_code == 200
    cells = resp.json()["data"]
    assert len(cells) == 4  # 4 个 POI 落在 4 个不同格点
    assert sum(cell["count"] for cell in cells) == 4
    assert all(cell["count"] == 1 for cell in cells)


def test_density_grid_returns_lat_lon_count(seeded):
    """每个格点字段为 {lat, lon, count}，可用于 Mapbox heatmap。"""
    resp = client.get("/api/analysis/density", params={**FULL_BBOX, "grid_size": 5})
    cell = resp.json()["data"][0]
    assert set(cell.keys()) == {"lat", "lon", "count"}


def test_density_invalid_bbox_422(seeded):
    """密度分析的非法包围盒同样返回统一 422。"""
    params = {"min_lon": 139.74, "min_lat": 35.71, "max_lon": 139.69, "max_lat": 35.66, "grid_size": 5}
    resp = client.get("/api/analysis/density", params=params)
    assert resp.status_code == 422
    assert resp.json()["code"] == 422
