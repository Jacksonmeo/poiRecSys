"""RecommendTool：返回模型 Top-K 推荐 POI（含解释字段）。

调用 recommend_service（摘要定位 + 详情组装），本文件不包含任何 SQL。
未指定 user_id/session_id 时自动取最近一个有推荐结果的会话。
候选附带派生解释字段（feature / reason），供 Agent 生成推荐解释。
"""

from sqlalchemy.orm import Session

from app.agent.registry import AgentTool
from app.core.config import settings
from app.services.recommend_service import get_recommendation, get_recommendations

_TOP_K_DEFAULT = 5
_TOP_K_MAX = 10


def _explain_candidates(candidates: list[dict], history: list[dict]) -> list[dict]:
    """为候选派生解释字段（feature / reason）。

    解释基于真实数据信号：模型排名/分数 + 与用户历史访问类别的关联，
    不编造信息。history 为推荐详情的已知历史轨迹（不含真实目标）。
    """
    history_categories = {point.get("venue_category") for point in history if point.get("venue_category")}
    history_names = [point.get("display_name") for point in history if point.get("display_name")]

    explained = []
    for candidate in candidates:
        category = candidate.get("venue_category") or ""
        rank = candidate.get("rank")
        score = candidate.get("score")
        reasons = []
        if rank == 1:
            reasons.append(f"模型评分最高（{score:.2f}）")
        if category and category in history_categories:
            reasons.append(f"与您历史访问过的类别「{category}」相关")
        if not reasons:
            reasons.append("基于您的历史签到序列的个性化预测")
        explained.append(
            {
                **candidate,
                "feature": {"rank": rank, "score": score, "category": category},
                "reason": "；".join(reasons),
            }
        )
    return explained


class RecommendTool(AgentTool):
    """返回某会话的 Top-K 推荐 POI（含排名与分数）。"""

    name = "recommend"
    description = "返回模型 Top-K 推荐 POI（可指定 user_id / session_id，缺省取最近会话）"
    parameters = {
        "type": "object",
        "properties": {
            "user_id": {"type": "string", "description": "用户 ID"},
            "session_id": {"type": "string", "description": "会话 ID"},
            "top_k": {"type": "integer", "description": "返回条数（1-10）", "default": 5},
        },
    }

    def run(self, db: Session, args: dict) -> dict:
        """返回指定（或最近）会话的 Top-K 推荐候选，附解释字段。"""
        args = self.validate(args)
        model_name = settings.recommendation_model_name
        user_id = args.get("user_id")
        session_id = args.get("session_id")
        top_k = min(args.get("top_k", _TOP_K_DEFAULT), _TOP_K_MAX)

        if not (user_id and session_id):
            summaries, _ = get_recommendations(db, model_name, limit=1)
            if not summaries:
                raise ValueError("数据库中暂无推荐结果。")
            user_id = summaries[0]["user_id"]
            session_id = summaries[0]["session_id"]

        detail = get_recommendation(db, user_id, session_id, model_name)
        if detail is None:
            raise ValueError(f"未找到会话 {session_id} 的推荐结果。")

        candidates = _explain_candidates(detail["candidates"][:top_k], detail["history"])
        return {
            "type": "recommend",
            "session_id": session_id,
            "top_k": len(candidates),
            "candidates": candidates,
        }
