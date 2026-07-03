import asyncio
import json
import unittest
from unittest.mock import MagicMock, patch

import app.services.query_service as query_service_module
from app.core.sql_guard import SQLSafetyError
from app.services.query_service import QueryService


class FakeGraph:
    def __init__(self, exc: Exception):
        self.exc = exc

    def astream(self, **kwargs):
        async def generator():
            raise self.exc
            yield  # pragma: no cover

        return generator()


class QueryServiceTests(unittest.TestCase):
    def test_query_service_returns_business_error_message_for_sql_safety(self):
        with patch.object(
            query_service_module,
            "graph",
            FakeGraph(SQLSafetyError("dangerous_keyword", "blocked", "delete from t")),
        ):
            service = QueryService(
                meta_mysql_repository=MagicMock(),
                embedding_client=MagicMock(),
                dw_mysql_repository=MagicMock(),
                column_qdrant_repository=MagicMock(),
                metric_qdrant_repository=MagicMock(),
                value_es_repository=MagicMock(),
            )

            async def collect():
                chunks = []
                async for chunk in service.query("统计销售额"):
                    chunks.append(chunk)
                return chunks

            chunks = asyncio.run(collect())

        payload = json.loads(chunks[0].removeprefix("data: ").strip())
        self.assertEqual(payload["type"], "error")
        self.assertEqual(
            payload["message"], "生成的 SQL 未通过安全校验，请调整问题后重试"
        )


if __name__ == "__main__":
    unittest.main()
