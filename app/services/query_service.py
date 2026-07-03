"""
问数查询服务

负责把 API 层传入的自然语言问题转换成一次 LangGraph 工作流执行：
创建初始 State、组装 Runtime Context、消费 graph.astream 的流式输出，
并统一包装成 SSE 文本返回给路由层。
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from app.agent.state import DataAgentState
from app.core.sql_guard import SQLSafetyError

if TYPE_CHECKING:
    from langchain_huggingface import HuggingFaceEndpointEmbeddings

    from app.repositories.es.value_es_repository import ValueESRepository
    from app.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository
    from app.repositories.mysql.meta.meta_mysql_repository import MetaMySQLRepository
    from app.repositories.qdrant.column_qdrant_repository import ColumnQdrantRepository
    from app.repositories.qdrant.metric_qdrant_repository import MetricQdrantRepository


graph = None


def get_graph():
    global graph
    if graph is None:
        from app.agent.graph import graph as compiled_graph

        graph = compiled_graph
    return graph


class QueryService:
    """封装一次问数查询所需的业务编排逻辑"""

    def __init__(
        self,
        meta_mysql_repository: MetaMySQLRepository,
        embedding_client: HuggingFaceEndpointEmbeddings,
        dw_mysql_repository: DWMySQLRepository,
        column_qdrant_repository: ColumnQdrantRepository,
        metric_qdrant_repository: MetricQdrantRepository,
        value_es_repository: ValueESRepository,
    ):
        # MySQL 仓储分别负责元数据补全和真实数仓环境信息读取
        self.meta_mysql_repository = meta_mysql_repository
        self.dw_mysql_repository = dw_mysql_repository

        # 召回链路依赖的向量检索、Embedding 和全文检索能力由依赖层注入
        self.embedding_client = embedding_client
        self.column_qdrant_repository = column_qdrant_repository
        self.metric_qdrant_repository = metric_qdrant_repository
        self.value_es_repository = value_es_repository

    async def query(self, query: str):
        """执行一次问数工作流，并逐段产出 SSE 消息"""

        # State 可以翻成“状态”：
        # 它保存的是这次问数任务过程中会不断变化的业务数据。
        # 外部工具对象不适合放进 State。
        state = DataAgentState(query=query)
        # Context 可以翻成“上下文”：
        # 它保存的是本次图执行需要复用的外部依赖，节点通过 runtime.context 读取。
        context = {
            "column_qdrant_repository": self.column_qdrant_repository,
            "embedding_client": self.embedding_client,
            "metric_qdrant_repository": self.metric_qdrant_repository,
            "value_es_repository": self.value_es_repository,
            "meta_mysql_repository": self.meta_mysql_repository,
            "dw_mysql_repository": self.dw_mysql_repository,
        }
        try:
            # stream_mode="custom" 对应节点内部 writer(...) 写出的进度消息。
            # 这一层做的是“把内部 LangGraph 流，翻译成对外 SSE 流”。
            async for chunk in get_graph().astream(
                input=state, context=context, stream_mode="custom"
            ):
                # SSE（服务端推送事件）要求每条消息以 data: 开头，并以两个换行符结束。
                # chunk 可以理解成“图执行过程中冒出来的一小段结构化消息”。
                # ensure_ascii=False 保留中文进度文案，default=str 兜底处理日期等非 JSON 类型
                yield f"data: {json.dumps(chunk, ensure_ascii=False, default=str)}\n\n"
        except SQLSafetyError as e:
            error = {"type": "error", "message": e.public_message}
            yield f"data: {json.dumps(error, ensure_ascii=False, default=str)}\n\n"
        except Exception as e:
            # 流式接口已经开始返回后不能再改 HTTP 状态码，因此把异常也包装成一条 SSE 消息。
            # 这就是流式接口和普通 JSON 接口最不一样的地方之一。
            # error 这里表示“整次查询最终失败的原因”，和单个步骤的 progress error 不是一回事。
            error = {"type": "error", "message": str(e)}
            yield f"data: {json.dumps(error, ensure_ascii=False, default=str)}\n\n"
