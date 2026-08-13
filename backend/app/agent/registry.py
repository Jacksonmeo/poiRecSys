"""Agent Tool 注册中心与统一接口（Stage 3）。

AgentTool 是所有工具的基类：name/description/parameters（JSON Schema）为元信息，
未来接入 LLM Function Calling 时可直接作为工具声明使用；run() 负责
参数验证 → 调用 service → 返回结构化结果。Tool 禁止直接写 SQL。
"""

from abc import ABC, abstractmethod
from typing import Any

from sqlalchemy.orm import Session


class AgentTool(ABC):
    """Tool 统一接口。"""

    name: str = ""
    description: str = ""
    parameters: dict[str, Any] = {}

    def validate(self, args: dict[str, Any]) -> dict[str, Any]:
        """轻量参数校验：必需字段存在 + 基本类型检查，非法时抛 ValueError。

        只保留 parameters 中声明过的字段，忽略多余参数。
        """
        properties = self.parameters.get("properties", {})
        required = self.parameters.get("required", [])
        for key in required:
            if key not in args:
                raise ValueError(f"缺少必需参数 '{key}'。")
        result = {key: value for key, value in args.items() if key in properties}
        for key, value in result.items():
            expected = properties[key].get("type")
            if expected == "string" and not isinstance(value, str):
                raise ValueError(f"参数 '{key}' 应为字符串。")
            if expected == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
                raise ValueError(f"参数 '{key}' 应为整数。")
            if expected == "number" and (not isinstance(value, (int, float)) or isinstance(value, bool)):
                raise ValueError(f"参数 '{key}' 应为数字。")
            if expected == "object" and not isinstance(value, dict):
                raise ValueError(f"参数 '{key}' 应为对象。")
        return result

    @abstractmethod
    def run(self, db: Session, args: dict[str, Any]) -> dict[str, Any]:
        """执行工具：参数验证 → 调用 service → 返回结构化结果。"""


class ToolRegistry:
    """工具注册表：按 name 索引工具实例。"""

    def __init__(self) -> None:
        """初始化空工具索引（工具名 → 工具实例）。"""
        self._tools: dict[str, AgentTool] = {}

    def register(self, tool: AgentTool) -> None:
        """注册工具；名称为空或重复时抛 ValueError。"""
        if not tool.name:
            raise ValueError("Tool name 不能为空。")
        self._tools[tool.name] = tool

    def get(self, name: str) -> AgentTool | None:
        """按工具名获取工具实例，不存在时返回 None。"""
        return self._tools.get(name)

    def all(self) -> list[AgentTool]:
        """返回全部已注册工具。"""
        return list(self._tools.values())
