"""
FastAPI 依赖组装

集中声明 API 层需要的依赖函数，把 Session、Repository、Client 和 Service
按职责组装起来。路由层只通过 Depends 声明自己需要什么对象，具体创建细节
都收敛在这里，避免 HTTP 处理函数直接感知底层基础设施。
"""

from typing import Annotated

from fastapi import Depends
from langchain_huggingface import HuggingFaceEndpointEmbeddings
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.embedding_client_manager import embedding_client_manager
from app.clients.es_client_manager import es_client_manager
from app.clients.mysql_client_manager import (
    dw_mysql_client_manager,
    meta_mysql_client_manager,
)
from app.clients.qdrant_client_manager import qdrant_client_manager
from app.repositories.es.value_es_repository import ValueESRepository
from app.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository
from app.repositories.mysql.meta.meta_mysql_repository import MetaMySQLRepository
from app.repositories.qdrant.column_qdrant_repository import ColumnQdrantRepository
from app.repositories.qdrant.metric_qdrant_repository import MetricQdrantRepository
from app.services.query_service import QueryService


async def get_meta_session():
    """创建一次请求内使用的元数据库 Session"""

    # Session 可以翻成“会话”：
    # 你可以把它理解成“一次请求里操作数据库时临时使用的工作上下文”。
    # yield 之后的清理逻辑由 async with 负责，FastAPI 会在请求结束后继续执行退出流程。
    async with meta_mysql_client_manager.session_factory() as meta_session:
        yield meta_session


async def get_meta_mysql_repository(
    session: Annotated[AsyncSession, Depends(get_meta_session)],
) -> MetaMySQLRepository:
    """基于请求级 Session 创建元数据仓储"""

    # Repository 可以翻成“仓储层”：
    # 它负责把“怎么查数据库”封装起来，避免路由和 Service 直接写 SQL。
    return MetaMySQLRepository(session)


async def get_embedding_client() -> HuggingFaceEndpointEmbeddings:
    """获取应用启动阶段初始化好的 Embedding 客户端"""

    return embedding_client_manager.client


async def get_dw_session():
    """创建一次请求内使用的数仓 Session"""

    # 元数据库 Session 和数仓 Session 分开，是因为它们面向两套不同用途的数据库。
    async with dw_mysql_client_manager.session_factory() as dw_session:
        yield dw_session


async def get_dw_mysql_repository(
    session: Annotated[AsyncSession, Depends(get_dw_session)],
) -> DWMySQLRepository:
    """基于请求级 Session 创建数仓仓储"""

    return DWMySQLRepository(session)


async def get_column_qdrant_repository() -> ColumnQdrantRepository:
    """创建字段向量检索仓储"""

    # 这里返回的是“字段向量仓储”，专门负责和 Qdrant 打交道。
    return ColumnQdrantRepository(qdrant_client_manager.client)


async def get_metric_qdrant_repository() -> MetricQdrantRepository:
    """创建指标向量检索仓储"""

    return MetricQdrantRepository(qdrant_client_manager.client)


async def get_value_es_repository() -> ValueESRepository:
    """创建字段取值全文检索仓储"""

    # ES 可以理解成全文检索引擎，这里主要负责字段值匹配。
    return ValueESRepository(es_client_manager.client)


async def get_query_service(
    meta_mysql_repository: Annotated[
        MetaMySQLRepository, Depends(get_meta_mysql_repository)
    ],
    embedding_client: Annotated[
        HuggingFaceEndpointEmbeddings, Depends(get_embedding_client)
    ],
    dw_mysql_repository: Annotated[DWMySQLRepository, Depends(get_dw_mysql_repository)],
    column_qdrant_repository: Annotated[
        ColumnQdrantRepository, Depends(get_column_qdrant_repository)
    ],
    metric_qdrant_repository: Annotated[
        MetricQdrantRepository, Depends(get_metric_qdrant_repository)
    ],
    value_es_repository: Annotated[ValueESRepository, Depends(get_value_es_repository)],
) -> QueryService:
    """组装一次查询所需的业务服务"""

    # Depends 可以翻成“依赖注入”：
    # 路由只声明“我需要 QueryService”，FastAPI 会沿着依赖树把它需要的对象都准备好。
    # QueryService 只接收已经创建好的依赖对象，本身不关心这些对象来自 MySQL、Qdrant 还是 ES。
    return QueryService(
        meta_mysql_repository=meta_mysql_repository,
        embedding_client=embedding_client,
        dw_mysql_repository=dw_mysql_repository,
        column_qdrant_repository=column_qdrant_repository,
        metric_qdrant_repository=metric_qdrant_repository,
        value_es_repository=value_es_repository,
    )
