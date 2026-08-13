"""统一 API 响应格式。

全链路约定：
    成功: {"code": 0, "message": "success", "data": {...}}
    失败: {"code": <HTTP状态码>, "message": "<错误描述>", "data": null}

所有 Router 返回值一律包成 ApiResponse，由 FastAPI response_model 完成序列化。
分页类响应将 {items, total, skip, limit} 作为 data 内层结构。
"""

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """统一响应外壳。"""

    code: int = 0
    message: str = "success"
    data: T | None = None


class PageData(BaseModel, Generic[T]):
    """分页数据结构，作为 ApiResponse.data 的内层载体。"""

    items: list[T]
    total: int
    skip: int
    limit: int
