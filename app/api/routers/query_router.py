"""
问数查询接口路由

负责定义前端访问的 `/api/query` 接口，把 HTTP 请求交给 QueryService，
并把问数智能体执行过程以 SSE 形式持续返回给客户端。
路由层只处理请求体、依赖声明和响应类型，不直接创建 Repository 或执行图节点。
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from starlette.responses import StreamingResponse

from app.api.dependencies import get_query_service
from app.api.schemas.query_schema import QuerySchema
from app.services.query_service import QueryService

# 当前模块只维护查询相关接口，避免后续所有 API 都挤在 main.py 中
query_router = APIRouter()


@query_router.post("/api/query")
async def query_handler(
    # 请求体参数：FastAPI 会把前端 JSON 自动解析成 QuerySchema
    query: QuerySchema,
    # 服务依赖：FastAPI 会调用 get_query_service，递归组装它所需的仓储和客户端。
    # 这里的 Depends 就是“依赖注入”，意思是：路由函数不负责自己造对象。
    query_service: Annotated[QueryService, Depends(get_query_service)],
):
    """接收用户自然语言问题，并流式返回 LangGraph 工作流输出"""

    # 第16章和第15章最大的差别就在这里：
    # 现在返回的已经不是 fake_streamer()，而是真实 QueryService.query(...) 驱动的问数工作流。
    return StreamingResponse(
        # query.query 是用户问题字符串；QueryService.query 返回异步生成器供响应逐段消费
        query_service.query(query.query),
        # text/event-stream 是 SSE（Server-Sent Events，服务端推送事件）协议要求的响应类型。
        media_type="text/event-stream",
    )
