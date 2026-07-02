import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock

from support import ensure_test_stubs

ensure_test_stubs()

from app.core.sql_guard import SQLGuard, SQLGuardConfig, SQLSafetyError
from app.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository


def build_guard(max_limit: int = 200) -> SQLGuard:
    return SQLGuard(
        SQLGuardConfig(
            enable=True,
            max_limit=max_limit,
            timeout_seconds=5,
            blocked_keywords=[
                "insert",
                "update",
                "delete",
                "drop",
                "alter",
                "truncate",
            ],
        )
    )


class DWMySQLRepositoryTests(unittest.TestCase):
    def test_validate_blocks_dangerous_sql_before_db_execute(self):
        session = AsyncMock()
        repository = DWMySQLRepository(session=session, sql_guard=build_guard())

        with self.assertRaises(SQLSafetyError):
            asyncio.run(repository.validate("delete from fact_order where id = 1"))

        session.execute.assert_not_awaited()

    def test_run_uses_normalized_sql_and_timeout(self):
        session = AsyncMock()
        mappings_result = MagicMock()
        mappings_result.fetchall.return_value = [{"amount": 10}]

        execute_calls = []

        async def execute_side_effect(statement):
            execute_calls.append(str(statement))
            if "MAX_EXECUTION_TIME" in str(statement):
                return AsyncMock()
            result = MagicMock()
            result.mappings.return_value = mappings_result
            return result

        session.execute.side_effect = execute_side_effect

        repository = DWMySQLRepository(session=session, sql_guard=build_guard())
        result = asyncio.run(repository.run("select * from fact_order"))

        self.assertEqual(result, [{"amount": 10}])
        self.assertIn("MAX_EXECUTION_TIME", execute_calls[0])
        self.assertEqual(
            execute_calls[1].lower(), "select * from fact_order limit 200"
        )


if __name__ == "__main__":
    unittest.main()
