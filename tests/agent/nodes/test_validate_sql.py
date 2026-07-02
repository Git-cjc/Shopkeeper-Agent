import asyncio
import unittest
from types import SimpleNamespace

from support import ensure_test_stubs

ensure_test_stubs()

from app.agent.nodes.validate_sql import validate_sql
from app.core.sql_guard import SQLSafetyError


class FakeRepository:
    def __init__(self, behavior):
        self.behavior = behavior

    async def validate(self, sql: str):
        if isinstance(self.behavior, Exception):
            raise self.behavior
        return self.behavior


def build_runtime(repo):
    events = []
    runtime = SimpleNamespace(
        stream_writer=events.append,
        context={"dw_mysql_repository": repo},
    )
    return runtime, events


class ValidateSQLNodeTests(unittest.TestCase):
    def test_validate_sql_re_raises_sql_safety_error(self):
        runtime, events = build_runtime(
            FakeRepository(
                SQLSafetyError("dangerous_keyword", "blocked", "delete from t")
            )
        )

        with self.assertRaises(SQLSafetyError):
            asyncio.run(validate_sql({"sql": "delete from t"}, runtime))

        self.assertEqual(
            events[0], {"type": "progress", "step": "校验SQL", "status": "running"}
        )
        self.assertEqual(
            events[-1], {"type": "progress", "step": "校验SQL", "status": "error"}
        )

    def test_validate_sql_returns_error_for_normal_sql_exception(self):
        runtime, events = build_runtime(FakeRepository(Exception("unknown column")))

        result = asyncio.run(validate_sql({"sql": "select bad"}, runtime))

        self.assertEqual(result, {"error": "unknown column"})
        self.assertEqual(
            events,
            [
                {"type": "progress", "step": "校验SQL", "status": "running"},
                {"type": "progress", "step": "校验SQL", "status": "success"},
            ],
        )


if __name__ == "__main__":
    unittest.main()
