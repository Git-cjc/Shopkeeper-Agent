import unittest

from app.core.sql_guard import SQLGuard, SQLGuardConfig, SQLSafetyError


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


class SQLGuardTests(unittest.TestCase):
    def test_allows_select_queries(self):
        guarded = build_guard().guard("select * from fact_order")
        self.assertTrue(guarded.normalized_sql.lower().endswith("limit 200"))

    def test_allows_with_select_queries(self):
        sql = "with top_orders as (select * from fact_order) select * from top_orders"
        guarded = build_guard().guard(sql)
        self.assertTrue(guarded.normalized_sql.lower().endswith("limit 200"))

    def test_blocks_delete_queries(self):
        with self.assertRaises(SQLSafetyError) as ctx:
            build_guard().guard("delete from fact_order where id = 1")
        self.assertEqual(ctx.exception.reason, "dangerous_keyword")

    def test_blocks_update_queries(self):
        with self.assertRaises(SQLSafetyError) as ctx:
            build_guard().guard("update fact_order set amount = 1 where id = 1")
        self.assertEqual(ctx.exception.reason, "dangerous_keyword")

    def test_blocks_drop_queries(self):
        with self.assertRaises(SQLSafetyError) as ctx:
            build_guard().guard("drop table fact_order")
        self.assertEqual(ctx.exception.reason, "dangerous_keyword")

    def test_appends_limit_when_missing(self):
        guarded = build_guard().guard("select * from fact_order")
        self.assertEqual(
            guarded.normalized_sql.lower(), "select * from fact_order limit 200"
        )

    def test_shrinks_large_simple_limit(self):
        guarded = build_guard().guard("select * from fact_order limit 1000")
        self.assertEqual(
            guarded.normalized_sql.lower(), "select * from fact_order limit 200"
        )

    def test_keeps_smaller_limit(self):
        guarded = build_guard().guard("select * from fact_order limit 50")
        self.assertEqual(
            guarded.normalized_sql.lower(), "select * from fact_order limit 50"
        )

if __name__ == "__main__":
    unittest.main()
