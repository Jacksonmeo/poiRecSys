"""SiteSelection 领域 Tool 到现有 AgentTool Runtime 的协议适配器。"""

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.agent.registry import AgentTool
from app.site_selection.schemas import SiteSelectionAnalyzeRequest
from app.site_selection.tools import SiteSelectionTool, SiteSelectionToolSchema


class SiteSelectionAgentTool(SiteSelectionToolSchema, AgentTool):
    """只转换 Agent 调用协议，不承担选址分析或数据访问职责。"""

    def __init__(self, site_selection_tool: SiteSelectionTool) -> None:
        """绑定领域 SiteSelectionTool（数据访问封装在领域服务内）。"""
        self.site_selection_tool = site_selection_tool

    def run(self, db: Session, args: dict) -> dict:
        """将 Agent 参数转换为领域调用，并导出 JSON 兼容结果。"""
        try:
            request = SiteSelectionAnalyzeRequest.model_validate(args)
        except ValidationError as error:
            raise ValueError(
                f"Invalid SiteSelectionAgentTool arguments: {error}"
            ) from error

        # 数据库依赖已封装在注入的领域 Service 中；db 仅用于兼容 AgentTool 接口。
        artifact = self.site_selection_tool.analyze(request.area_ids)
        return artifact.model_dump(mode="json")
