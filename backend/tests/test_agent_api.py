"""Stage 3 Agent 接口测试：意图路由 + 工具执行闭环。

seeded fixture 提供 1 个咖啡店（poi_coffee）、3 个推荐候选、3 个轨迹点。
"""

from tests.conftest import client


def test_agent_coffee_query(seeded):
    """「找咖啡店」→ query_poi + poi 地图图层。"""
    resp = client.post("/api/agent/chat", json={"message": "帮我找咖啡店"})
    assert resp.status_code == 200
    data = resp.json()["data"]

    assert data["tool_calls"][0]["tool"] == "query_poi"
    assert data["tool_calls"][0]["args"]["category"] == "Coffee Shop"

    poi_layer = next(layer for layer in data["map_layers"] if layer["type"] == "poi")
    venue_ids = {p["venue_id"] for p in poi_layer["data"]}
    assert "poi_coffee" in venue_ids
    assert "POI" in data["reply"]


def test_agent_spatial_density(seeded):
    """「空间密度」→ spatial_density + heatmap 图层。"""
    resp = client.post("/api/agent/chat", json={"message": "东京中心的空间密度热力"})
    assert resp.status_code == 200
    data = resp.json()["data"]

    assert data["tool_calls"][0]["tool"] == "spatial_density"
    heatmap = next(layer for layer in data["map_layers"] if layer["type"] == "heatmap")
    assert len(heatmap["data"]) > 0
    cell = heatmap["data"][0]
    assert set(cell.keys()) == {"lat", "lon", "count"}
    assert "热力" in data["reply"]


def test_agent_recommend(seeded):
    """「推荐」→ recommend + poi 图层（含 rank/score）。"""
    resp = client.post("/api/agent/chat", json={"message": "给我推荐"})
    assert resp.status_code == 200
    data = resp.json()["data"]

    assert data["tool_calls"][0]["tool"] == "recommend"
    poi_layer = next(layer for layer in data["map_layers"] if layer["type"] == "poi")
    candidates = poi_layer["data"]
    assert len(candidates) == 3  # seed 提供 3 个候选
    assert "rank" in candidates[0] and "score" in candidates[0]
    assert "Top" in data["reply"]


def test_agent_track(seeded):
    """「轨迹」→ track + trajectory 图层。"""
    resp = client.post("/api/agent/chat", json={"message": "查看轨迹"})
    assert resp.status_code == 200
    data = resp.json()["data"]

    assert data["tool_calls"][0]["tool"] == "track"
    traj_layer = next(layer for layer in data["map_layers"] if layer["type"] == "trajectory")
    points = traj_layer["data"]
    assert len(points) == 3
    assert "sequence_no" in points[0] and "venue_id" in points[0]
    assert "轨迹" in data["reply"]


def test_agent_fallback_no_tool_call(seeded):
    """未识别意图 → 兜底回复，无工具调用、无地图图层。"""
    resp = client.post("/api/agent/chat", json={"message": "你好"})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["tool_calls"] == []
    assert data["map_layers"] == []
    assert "查询" in data["reply"]


def test_agent_empty_message_422():
    """空白消息 → 统一 422 格式。"""
    resp = client.post("/api/agent/chat", json={"message": "   "})
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == 422
    assert body["data"] is None


def test_agent_site_selection_returns_structured_artifact(seeded):
    """选址意图 → 请求级 SiteSelection Tool → Artifact → 最终总结。"""
    resp = client.post(
        "/api/agent/chat",
        json={"message": "比较新宿和涩谷的咖啡店选址"},
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["tool_calls"] == [
        {
            "tool": "analyze_site_selection",
            "args": {"area_ids": ["shinjuku", "shibuya"]},
        }
    ]
    assert data["reply"]
    assert data["artifacts"][0]["type"] == "site_selection"
    artifact = data["artifacts"][0]["data"]
    assert artifact["analysis_type"] == "site_selection"
    assert [area["area_id"] for area in artifact["candidate_areas"]] == [
        "shinjuku",
        "shibuya",
    ]
