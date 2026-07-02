"""
FastAPI 应用入口

负责创建后端应用实例，注册应用生命周期函数，并把各业务模块中的 router
挂载到同一个 app 上。HTTP 请求会先进入这里创建的 app，再按路由分发到
具体的接口处理函数。
"""

import uuid

from fastapi import FastAPI, Request

from app.api.lifespan import lifespan
from app.api.routers.query_router import query_router
from app.core.context import request_id_ctx_var

# lifespan 可以翻成“生命周期函数”：
# 也就是服务启动前做什么、服务关闭前做什么，都统一放在这里管理。
# main.py 只负责把这些能力装配到 FastAPI 应用上。
app = FastAPI(lifespan=lifespan)

# 把查询路由注册进应用；没有挂载时，/docs 和真实 HTTP 请求都访问不到该接口。
# include_router 可以理解成“把这组接口接到总应用上”。
app.include_router(query_router)


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    """为每个 HTTP 请求生成 request_id，方便整条链路日志追踪"""

    # middleware 可以翻成“中间件”：
    # 它会在真正进入路由函数前后插入一层统一逻辑。
    # 这里的作用是给每个请求生成唯一 request_id，方便后续日志追踪。
    # 请求被处理之前
    # uuid 可以翻成“通用唯一标识”：
    # 这里把它当成“这次请求的编号”即可。
    request_id = uuid.uuid4()
    request_id_ctx_var.set(request_id)
    # call_next 表示“把请求继续交给后面的路由处理逻辑”
    response = await call_next(request)
    # 请求被处理之后
    return response
