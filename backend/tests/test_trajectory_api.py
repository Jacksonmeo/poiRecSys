"""用户 / 轨迹接口测试：用户搜索、签到、会话列表、会话轨迹。"""

from tests.conftest import client


def test_list_users(seeded):
    """用户列表分页 + 统一格式。"""
    resp = client.get("/api/users", params={"limit": 10})
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    data = body["data"]
    assert data["total"] == 2
    assert {item["user_id"] for item in data["items"]} == {"user_1", "user_2"}


def test_list_users_keyword_search(seeded):
    """按 user_id 关键字模糊搜索。"""
    resp = client.get("/api/users", params={"keyword": "user_1"})
    data = resp.json()["data"]
    assert data["total"] == 1
    assert data["items"][0]["user_id"] == "user_1"


def test_user_checkins(seeded):
    """用户签到列表，JOIN POI 返回展示信息。"""
    resp = client.get("/api/users/user_1/checkins")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    checkins = body["data"]
    assert len(checkins) == 3
    # 按时间升序
    timestamps = [c["utc_timestamp"] for c in checkins]
    assert timestamps == sorted(timestamps)
    # JOIN 到 POI 展示名
    assert checkins[0]["display_name"] == "Central Coffee"


def test_user_checkins_unknown_user_returns_empty(seeded):
    """不存在的用户返回空列表而非 404（兼容旧前端行为）。"""
    resp = client.get("/api/users/ghost/checkins")
    assert resp.status_code == 200
    assert resp.json()["data"] == []


def test_user_sessions(seeded):
    """用户会话列表分页。"""
    resp = client.get("/api/users/user_1/sessions")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    data = body["data"]
    assert data["total"] == 1
    assert data["items"][0]["session_id"] == "sess_001"
    assert data["items"][0]["checkin_count"] == 3


def test_user_sessions_not_found_404(seeded):
    """不存在的用户返回 404。"""
    resp = client.get("/api/users/ghost/sessions")
    assert resp.status_code == 404
    assert resp.json()["code"] == 404


def test_session_trajectory(seeded):
    """会话轨迹：返回会话摘要 + 按顺序排列的轨迹点。"""
    resp = client.get("/api/sessions/sess_001/trajectory")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    data = body["data"]
    assert data["session"]["session_id"] == "sess_001"
    points = data["points"]
    assert [p["sequence_no"] for p in points] == [1, 2, 3]
    assert points[0]["venue_id"] == "poi_coffee"
    assert "longitude" in points[0] and "latitude" in points[0]


def test_session_trajectory_not_found_404(seeded):
    """不存在的会话返回 404。"""
    resp = client.get("/api/sessions/ghost/trajectory")
    assert resp.status_code == 404
    assert resp.json()["code"] == 404
