"""推荐结果 Pydantic 模型：定义推荐相关接口的 ApiResponse.data 内层结构。"""

from pydantic import BaseModel


class RecommendationSummary(BaseModel):
    """推荐 session 摘要：每个 session 一条，用于列表页。"""

    user_id: str
    session_id: str
    target_poi_id: str
    top_k: int
