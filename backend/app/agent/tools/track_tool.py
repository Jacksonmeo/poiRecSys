"""TrackTool：查询会话轨迹（签到序列）。

调用 session_service（会话定位 + 轨迹点查询）与 user_service（默认用户），
本文件不包含任何 SQL。轨迹点字段与 /api/sessions/{sid}/trajectory 保持同构。
"""

from sqlalchemy.orm import Session

from app.agent.registry import AgentTool
from app.services.session_service import get_session_by_id, get_session_points, get_user_sessions
from app.services.user_service import get_users


class TrackTool(AgentTool):
    """按会话查询轨迹点序列（未指定时取最近会话）。"""

    name = "track"
    description = "查询会话轨迹（签到序列）：可指定 user_id / session_id，缺省取最近会话"
    parameters = {
        "type": "object",
        "properties": {
            "user_id": {"type": "string", "description": "用户 ID"},
            "session_id": {"type": "string", "description": "会话 ID"},
        },
    }

    def run(self, db: Session, args: dict) -> dict:
        """查询指定（或最近）会话的轨迹点序列并补全序号。"""
        args = self.validate(args)
        user_id = args.get("user_id")
        session_id = args.get("session_id")

        if not session_id:
            if not user_id:
                users, _ = get_users(db, keyword=None, skip=0, limit=1)
                if not users:
                    raise ValueError("数据库中暂无用户。")
                user_id = users[0].user_id
            sessions, _ = get_user_sessions(db, user_id, skip=0, limit=1)
            if not sessions:
                raise ValueError(f"用户 {user_id} 暂无会话。")
            session_id = sessions[0].session_id

        if get_session_by_id(db, session_id) is None:
            raise ValueError(f"会话 {session_id} 不存在。")

        rows = get_session_points(db, session_id)
        points = []
        for index, row in enumerate(rows, start=1):
            payload = dict(row._mapping)
            if not payload.get("sequence_no"):
                payload["sequence_no"] = index
            points.append(payload)

        return {"type": "track", "session_id": session_id, "points": points}
