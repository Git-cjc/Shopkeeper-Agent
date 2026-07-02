"""
数仓 MySQL 仓储

这一层对应文档里的 DW Repository，职责是到真实数仓中补齐配置文件里
没有显式维护的信息，例如字段类型和字段示例值。Service 层只关心
“需要哪些信息”，具体怎样查数仓由仓储层统一封装
SQL 生成闭环中的数据库环境读取 SQL 校验和最终查询执行也集中放在这里
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.log import logger
from app.core.sql_guard import SQLGuard, GuardedSQL


class DWMySQLRepository:
    """负责查询数仓真实表结构和字段样例值"""

    def __init__(self, session: AsyncSession, sql_guard: SQLGuard | None = None):
        self.session = session
        if sql_guard is None:
            from app.conf.app_config import app_config

            sql_guard = SQLGuard(app_config.sql_guard)
        self.sql_guard = sql_guard

    async def get_column_types(self, table_name: str) -> dict[str, str]:
        """查询整张表的字段类型，作为 ColumnInfo.type 的真实来源"""
        sql = f"show columns from {table_name}"
        result = await self.session.execute(text(sql))
        result_dict = result.mappings().fetchall()
        return {row["Field"]: row["Type"] for row in result_dict}

    async def get_column_values(
        self, table_name: str, column_name: str, limit: int = 10
    ) -> list:
        """抽样查询字段示例值，供元数据入库和后续检索链路复用"""
        sql = f"select distinct {column_name} from {table_name} limit {limit}"
        result = await self.session.execute(text(sql))
        return [row[0] for row in result.fetchall()]

    async def get_db_info(self):
        """读取当前数仓数据库的方言和版本，供 SQL 生成提示词使用"""

        sql = "select version()"
        result = await self.session.execute(text(sql))
        version = result.scalar()

        # dialect 来自 SQLAlchemy 当前绑定的数据库方言，例如 mysql
        dialect = self.session.bind.dialect.name
        return {"dialect": dialect, "version": version}

    async def validate(self, sql: str):
        """用 EXPLAIN 让数据库提前解析 SQL，发现语法 表名 字段名等错误"""
        guarded = self._guard_sql(sql, operation="validate")
        sql = f"explain {guarded.normalized_sql}"
        await self.session.execute(text(sql))

    async def run(self, sql: str) -> list[dict]:
        """执行最终 SQL，并把 SQLAlchemy 行对象转换成前端更易消费的字典列表"""
        guarded = self._guard_sql(sql, operation="run")
        await self._apply_timeout()
        result = await self.session.execute(text(guarded.normalized_sql))
        return [dict(row) for row in result.mappings().fetchall()]

    def _guard_sql(self, sql: str, operation: str) -> GuardedSQL:
        try:
            guarded = self.sql_guard.guard(sql)
        except Exception as exc:
            if hasattr(exc, "reason"):
                logger.warning(
                    f"SQL安全拦截 operation={operation} reason={exc.reason} sql={sql}"
                )
            raise

        if guarded.normalized_sql != guarded.original_sql:
            logger.info(
                "SQL安全规范化 operation={} original_sql={} normalized_sql={}".format(
                    operation, guarded.original_sql, guarded.normalized_sql
                )
            )
        return guarded

    async def _apply_timeout(self):
        timeout_ms = self.sql_guard.config.timeout_seconds * 1000
        await self.session.execute(text(f"SET SESSION MAX_EXECUTION_TIME={timeout_ms}"))
