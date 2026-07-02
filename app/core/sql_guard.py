"""
SQL 安全防护

在最终访问数仓前，对生成的 SQL 做只读校验、危险关键词拦截和 LIMIT 规范化。
这层只负责策略判断，不直接操作数据库连接。
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class SQLGuardConfig:
    """SQL 安全防护配置"""

    enable: bool
    max_limit: int
    timeout_seconds: int
    blocked_keywords: list[str]


@dataclass
class GuardedSQL:
    """通过安全校验后的 SQL 结果"""

    original_sql: str
    normalized_sql: str


class SQLSafetyError(Exception):
    """SQL 未通过安全校验时抛出的异常"""

    default_public_message = "生成的 SQL 未通过安全校验，请调整问题后重试"

    def __init__(
        self,
        reason: str,
        detail: str,
        sql: str,
        normalized_sql: str | None = None,
        public_message: str | None = None,
    ):
        super().__init__(detail)
        self.reason = reason
        self.detail = detail
        self.sql = sql
        self.normalized_sql = normalized_sql
        self.public_message = public_message or self.default_public_message


class SQLGuard:
    """负责对候选 SQL 做只读校验和 LIMIT 规范化"""

    def __init__(self, config: SQLGuardConfig):
        self.config = config
        self._blocked_keyword_pattern = re.compile(
            r"\b(" + "|".join(re.escape(word) for word in config.blocked_keywords) + r")\b",
            re.IGNORECASE,
        )

    def guard(self, sql: str) -> GuardedSQL:
        """校验 SQL 安全性，并返回最终可执行 SQL"""

        normalized_sql = self._strip_trailing_semicolon(sql)
        if not self.config.enable:
            return GuardedSQL(original_sql=sql, normalized_sql=normalized_sql)

        if ";" in normalized_sql:
            raise SQLSafetyError(
                reason="multiple_statements",
                detail="multiple statements are not allowed",
                sql=sql,
            )

        sql_without_literals = self._strip_string_literals(normalized_sql)
        blocked = self._blocked_keyword_pattern.search(sql_without_literals)
        if blocked:
            raise SQLSafetyError(
                reason="dangerous_keyword",
                detail=f"blocked keyword detected: {blocked.group(1)}",
                sql=sql,
            )

        if not self._is_readonly_query(sql_without_literals):
            raise SQLSafetyError(
                reason="non_readonly",
                detail="only readonly select queries are allowed",
                sql=sql,
            )

        normalized_sql = self._normalize_limit(normalized_sql)
        return GuardedSQL(original_sql=sql, normalized_sql=normalized_sql)

    @staticmethod
    def _strip_trailing_semicolon(sql: str) -> str:
        return sql.strip().rstrip(";").strip()

    @staticmethod
    def _strip_string_literals(sql: str) -> str:
        sql = re.sub(r"'(?:''|[^'])*'", "''", sql)
        sql = re.sub(r'"(?:""|[^"])*"', '""', sql)
        return sql

    @staticmethod
    def _is_readonly_query(sql_without_literals: str) -> bool:
        lowered = sql_without_literals.lstrip().lower()
        return lowered.startswith("select ") or lowered.startswith("with ")

    def _normalize_limit(self, sql: str) -> str:
        sql = self._normalize_limit_comma_style(sql)
        sql = self._normalize_limit_offset_style(sql)
        sql = self._normalize_limit_simple_style(sql)
        if re.search(r"\blimit\b", sql, re.IGNORECASE):
            return sql
        return f"{sql} limit {self.config.max_limit}"

    def _normalize_limit_comma_style(self, sql: str) -> str:
        pattern = re.compile(r"\blimit\s+(\d+)\s*,\s*(\d+)\b", re.IGNORECASE)
        match = pattern.search(sql)
        if not match:
            return sql
        offset, count = int(match.group(1)), int(match.group(2))
        if count <= self.config.max_limit:
            return sql
        replacement = f"limit {offset}, {self.config.max_limit}"
        return pattern.sub(replacement, sql, count=1)

    def _normalize_limit_offset_style(self, sql: str) -> str:
        pattern = re.compile(r"\blimit\s+(\d+)\s+offset\s+(\d+)\b", re.IGNORECASE)
        match = pattern.search(sql)
        if not match:
            return sql
        count, offset = int(match.group(1)), int(match.group(2))
        if count <= self.config.max_limit:
            return sql
        replacement = f"limit {self.config.max_limit} offset {offset}"
        return pattern.sub(replacement, sql, count=1)

    def _normalize_limit_simple_style(self, sql: str) -> str:
        pattern = re.compile(r"\blimit\s+(\d+)\b", re.IGNORECASE)
        match = pattern.search(sql)
        if not match:
            return sql
        count = int(match.group(1))
        if count <= self.config.max_limit:
            return sql
        replacement = f"limit {self.config.max_limit}"
        return pattern.sub(replacement, sql, count=1)
