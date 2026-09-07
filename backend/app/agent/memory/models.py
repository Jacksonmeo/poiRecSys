"""结构化任务上下文、会话摘要及其确定性更新规则。"""

from __future__ import annotations

from typing import Any, TypedDict, cast

from app.llm.schemas import LLMMessage, LLMToolCall

MAX_RECENT_MESSAGES = 24
MAX_SUMMARY_ITEMS = 12
MAX_ARTIFACT_REFS = 20
_TOKYO_LOCATIONS = {
    "东京",
    "东京中心",
    "tokyo",
    "tokyo center",
    "涩谷",
    "shibuya",
    "新宿",
    "shinjuku",
    "银座",
    "ginza",
    "浅草",
    "asakusa",
    "池袋",
    "ikebukuro",
}


class TaskContext(TypedDict, total=False):
    """当前空间分析任务中可直接复用的参数与结果引用。"""

    city: str
    current_area: str
    business_type: str
    search_radius_m: int
    candidate_areas: list[str]
    last_tool: str
    last_tool_args: dict[str, Any]
    last_artifact_id: str


class ConversationSummary(TypedDict):
    """面向恢复和压缩的结构化摘要，避免生成散文式总结。"""

    completed_actions: list[str]
    active_assumptions: list[str]
    selected_areas: list[str]
    important_tool_results: list[dict[str, Any]]
    unresolved_questions: list[str]
    next_goal: str


def empty_conversation_summary() -> ConversationSummary:
    """返回互不共享可变字段的空摘要。"""
    return {
        "completed_actions": [],
        "active_assumptions": [],
        "selected_areas": [],
        "important_tool_results": [],
        "unresolved_questions": [],
        "next_goal": "",
    }


def merge_recent_messages(
    current: list[LLMMessage] | None,
    updates: list[LLMMessage] | None,
) -> list[LLMMessage]:
    """合并消息并只在检查点中保留最近消息，长期信息由结构化摘要承担。"""
    messages = [*(current or []), *(updates or [])][-MAX_RECENT_MESSAGES:]
    while messages and messages[0].role == "tool":
        messages.pop(0)
    return messages


def update_task_context(
    current: TaskContext | None,
    call: LLMToolCall,
    tool_summary: dict[str, Any],
    artifact_id: str,
) -> TaskContext:
    """根据已验证的工具调用更新任务状态，不从自由文本中臆测参数。"""
    context = cast(TaskContext, dict(current or {}))
    args = call.arguments
    location = call.context.get("location")
    if location:
        context["current_area"] = str(location)
        if str(location).strip().lower() in _TOKYO_LOCATIONS:
            context["city"] = "东京"
    if args.get("category"):
        context["business_type"] = str(args["category"])
    if isinstance(args.get("radius_m"), int):
        context["search_radius_m"] = args["radius_m"]
    area_ids = args.get("area_ids")
    if isinstance(area_ids, list):
        context["candidate_areas"] = [str(area_id) for area_id in area_ids]
    context.update(
        {
            "last_tool": call.name,
            "last_tool_args": _public_args(args),
            "last_artifact_id": artifact_id,
        }
    )
    if tool_summary.get("candidate_areas"):
        context["candidate_areas"] = list(tool_summary["candidate_areas"])
    return context


def update_conversation_summary(
    current: ConversationSummary | None,
    executions: list[dict[str, Any]],
    task_context: TaskContext | None,
    input_message: str,
) -> ConversationSummary:
    """把本轮动作与关键结果合并进固定结构，并限制列表增长。"""
    summary = empty_conversation_summary()
    if current:
        summary.update(current)

    completed = list(summary["completed_actions"])
    important = list(summary["important_tool_results"])
    for execution in executions:
        name = str(execution.get("name", ""))
        artifact_id = str(execution.get("artifact_id", ""))
        completed.append(f"{name} -> {artifact_id}" if artifact_id else name)
        result = execution.get("result")
        if isinstance(result, dict):
            important.append(result)

    selected = list((task_context or {}).get("candidate_areas", []))
    summary["completed_actions"] = completed[-MAX_SUMMARY_ITEMS:]
    summary["important_tool_results"] = important[-MAX_SUMMARY_ITEMS:]
    summary["selected_areas"] = selected[-MAX_SUMMARY_ITEMS:]
    summary["next_goal"] = input_message[:500]
    return summary


def merge_artifact_refs(current: list[str], artifact_id: str) -> list[str]:
    """追加并去重 artifact 引用，保留最近固定数量。"""
    refs = [item for item in current if item != artifact_id]
    refs.append(artifact_id)
    return refs[-MAX_ARTIFACT_REFS:]


def _public_args(args: dict[str, Any]) -> dict[str, Any]:
    """去掉仅供内部上下文使用的参数。"""
    return {key: value for key, value in args.items() if not key.startswith("_")}
