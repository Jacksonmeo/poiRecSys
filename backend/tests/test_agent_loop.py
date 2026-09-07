"""AgentRunner（LangGraph 编排）与 Artifact 输出测试。"""

import json
from unittest.mock import Mock

from sqlalchemy.orm import Session

from app.agent.graph.runner import AgentLoopEvent, AgentRunner
from app.agent.registry import AgentTool, ToolRegistry
from app.agent.router_llm import LLMIntentRouter
from app.agent.service import AgentService
from app.llm.client import LLMClient
from app.llm.schemas import LLMResponse, LLMToolCall


class _ArtifactTool(AgentTool):
    name = "analyze_site_selection"
    description = "test tool"
    parameters = {
        "type": "object",
        "properties": {"area_ids": {"type": "array"}},
        "required": ["area_ids"],
    }

    def __init__(self) -> None:
        self.calls = 0

    def run(self, db: Session, args: dict) -> dict:
        self.calls += 1
        return {
            "analysis_type": "site_selection",
            "candidate_areas": [
                {"area_id": area_id, "display_name": area_id.title()}
                for area_id in args["area_ids"]
            ],
            "metadata": {
                "config_version": "tokyo_coffee_v1",
                "dataset": "TSMC2014_TKY",
                "observation_period": None,
            },
            "metrics": [],
            "flows": [],
            "summary": None,
        }


class _TwoTurnClient(LLMClient):
    name = "two_turn"

    def __init__(self) -> None:
        self.messages = []

    def complete(self, messages, tools=None):
        self.messages.append(list(messages))
        if messages[-1].role == "user":
            return LLMResponse(
                tool_calls=[
                    LLMToolCall(
                        id="call-site-selection",
                        name="analyze_site_selection",
                        arguments={"area_ids": ["shinjuku", "shibuya"]},
                    )
                ]
            )
        return LLMResponse(text="已完成两个候选区的空间事实分析。")


def _runtime() -> tuple[AgentRunner, _ArtifactTool, _TwoTurnClient, ToolRegistry]:
    tool = _ArtifactTool()
    registry = ToolRegistry()
    registry.register(tool)
    client = _TwoTurnClient()
    router = LLMIntentRouter(registry, client=client)
    runner = AgentRunner(
        registry=registry,
        router=router,
        fallback_reply=lambda _name, _result: "fallback",
    )
    return runner, tool, client, registry


def test_runner_returns_tool_result_to_llm_before_final_summary() -> None:
    runner, tool, client, _registry = _runtime()

    result = runner.run(Mock(spec=Session), "比较新宿和涩谷的选址")

    assert result.reply == "已完成两个候选区的空间事实分析。"
    assert tool.calls == 1
    assert len(client.messages) == 2
    second_turn = client.messages[1]
    assert second_turn[-2].role == "assistant"
    assert second_turn[-2].tool_calls[0].id == "call-site-selection"
    assert second_turn[-1].role == "tool"
    assert second_turn[-1].tool_call_id == "call-site-selection"
    assert json.loads(second_turn[-1].content)["analysis_type"] == "site_selection"


def test_runner_iter_run_emits_tool_call_then_tool_result() -> None:
    runner, tool, _client, _registry = _runtime()

    events: list[AgentLoopEvent] = []
    iterator = runner.iter_run(Mock(spec=Session), "比较新宿和涩谷的选址")
    while True:
        try:
            events.append(next(iterator))
        except StopIteration as stop:
            result = stop.value
            break

    assert [event.kind for event in events] == ["tool_call", "tool_result"]
    assert events[0].name == "analyze_site_selection"
    assert events[0].args == {"area_ids": ["shinjuku", "shibuya"]}
    assert events[1].result["analysis_type"] == "site_selection"
    assert result.reply == "已完成两个候选区的空间事实分析。"
    assert len(result.executions) == 1


def test_agent_service_preserves_site_selection_artifact() -> None:
    _runner, _tool, client, registry = _runtime()
    service = AgentService(
        registry=registry,
        db=Mock(spec=Session),
        router=LLMIntentRouter(registry, client=client),
    )

    response = service.chat(message="比较候选区选址")

    assert response.reply == "已完成两个候选区的空间事实分析。"
    assert response.tool_calls[0].tool == "analyze_site_selection"
    assert response.artifacts[0].type == "site_selection"
    assert response.artifacts[0].data["analysis_type"] == "site_selection"


def test_runner_stops_repeated_identical_tool_call() -> None:
    class _RepeatingClient(LLMClient):
        name = "repeating"

        def complete(self, messages, tools=None):
            return LLMResponse(
                tool_calls=[
                    LLMToolCall(
                        name="analyze_site_selection",
                        arguments={"area_ids": ["shinjuku"]},
                    )
                ]
            )

    tool = _ArtifactTool()
    registry = ToolRegistry()
    registry.register(tool)
    runner = AgentRunner(
        registry=registry,
        router=LLMIntentRouter(registry, client=_RepeatingClient()),
        fallback_reply=lambda name, result: f"fallback:{name}",
        max_steps=3,
    )

    result = runner.run(Mock(spec=Session), "分析新宿选址")

    assert tool.calls == 1
    assert result.reply == "fallback:analyze_site_selection"
