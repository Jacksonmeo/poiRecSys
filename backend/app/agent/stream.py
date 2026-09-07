"""Agent SSE 流式事件与格式化（Stage 4 Step 6）。

chat_stream 编排过程中的事件序列：
  tool_call → tool_result → text（增量）→ done（终态，含 reply / tool_calls / map_layers）
  工具执行异常时发出 error 事件（HTTP 状态码保持 200，错误走事件通道）。
"""

import json
from dataclasses import dataclass, field


@dataclass
class ChatStreamEvent:
    """一次 SSE 事件：类型 + 业务载荷。"""

    kind: str
    payload: dict = field(default_factory=dict)


def sse_format(event: ChatStreamEvent) -> str:
    """事件 → SSE 文本块（event: kind + data: JSON）。

    default=str 兜底：轨迹点 utc_timestamp 等 datetime 值序列化为可读字符串。
    """
    data = json.dumps(event.payload, ensure_ascii=False, default=str)
    return f"event: {event.kind}\ndata: {data}\n\n"


def chunk_text(text: str, size: int = 6) -> list[str]:
    """把回复文本切块，模拟流式打字机效果。"""
    return [text[index : index + size] for index in range(0, len(text), size)]


def tool_result_summary(tool_name: str, result: dict) -> dict:
    """工具执行结果 → 业务摘要（只含数量等汇总，不含内部数据细节）。"""
    if tool_name == "analyze_site_selection":
        return {
            "area_count": len(result.get("candidate_areas", [])),
            "metric_count": len(result.get("metrics", [])),
            "flow_count": len(result.get("flows", [])),
        }
    if tool_name == "spatial_density":
        return {"count": result.get("count", 0)}
    if tool_name == "recommend":
        return {
            "count": len(result.get("candidates", [])),
            "session_id": result.get("session_id", ""),
        }
    if tool_name == "track":
        return {"count": len(result.get("points", [])), "session_id": result.get("session_id", "")}
    # query_poi：feature_collection（GeoJSON）或 poi_list
    data = result.get("data") or {}
    if result.get("type") == "feature_collection":
        count = len(data.get("features", []))
    else:
        count = len(data) if isinstance(data, list) else 0
    return {"count": count}
