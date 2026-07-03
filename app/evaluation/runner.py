from __future__ import annotations

import json
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from app.evaluation.dataset import load_eval_cases
from app.evaluation.models import QueryEvalCase
from app.evaluation.scoring import (
    compare_column_names,
    compare_result_values,
    compare_results,
    score_recall,
)

if TYPE_CHECKING:
    from app.agent.context import DataAgentContext
    from app.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository
else:
    DataAgentContext = Any
    DWMySQLRepository = Any


def _missing_manager() -> SimpleNamespace:
    async def _close() -> None:
        return None

    return SimpleNamespace(
        engine=None,
        client=None,
        session_factory=None,
        init=lambda: None,
        close=_close,
    )


try:
    from app.clients.embedding_client_manager import embedding_client_manager
    from app.clients.es_client_manager import es_client_manager
    from app.clients.mysql_client_manager import (
        dw_mysql_client_manager,
        meta_mysql_client_manager,
    )
    from app.clients.qdrant_client_manager import qdrant_client_manager
except ImportError:
    embedding_client_manager = _missing_manager()
    es_client_manager = _missing_manager()
    meta_mysql_client_manager = _missing_manager()
    dw_mysql_client_manager = _missing_manager()
    qdrant_client_manager = _missing_manager()


@dataclass(slots=True)
class QueryEvalResult:
    case_id: str
    question: str
    generated_sql: str | None
    reference_sql: str
    execution_success: bool
    sql_correct: bool
    strict_sql_correct: bool
    alias_consistent: bool
    generated_result: list[dict[str, object]] | None
    reference_result: list[dict[str, object]]
    retrieved_table_ids: list[str]
    retrieved_column_ids: list[str]
    retrieved_metric_ids: list[str]
    retrieved_value_ids: list[str]
    table_recall_hit: bool
    column_recall_hit: bool
    metric_recall_hit: bool
    value_recall_hit: bool
    full_recall_hit: bool
    error_message: str | None
    tags: list[str]


@dataclass(slots=True)
class QueryEvalSummary:
    total_cases: int
    sql_accuracy: float
    strict_sql_accuracy: float
    alias_consistency_rate: float
    execution_success_rate: float
    table_recall_coverage: float
    column_recall_coverage: float
    metric_recall_coverage: float
    value_recall_coverage: float
    full_recall_rate: float
    by_tag: dict[str, dict[str, float]]


def build_eval_result(
    case: QueryEvalCase,
    final_state: dict[str, Any],
    reference_result: list[dict[str, object]],
) -> QueryEvalResult:
    generated_sql = final_state.get("sql")
    generated_result = final_state.get("execution_result")
    execution_error = final_state.get("execution_error")

    retrieved_table_ids = _extract_table_ids(final_state)
    retrieved_column_ids = _extract_ids(final_state.get("retrieved_column_infos", []))
    retrieved_metric_ids = _extract_ids(final_state.get("retrieved_metric_infos", []))
    retrieved_value_ids = _extract_ids(final_state.get("retrieved_value_infos", []))

    table_recall_hit = score_recall(case.expected_tables, retrieved_table_ids)
    column_recall_hit = score_recall(case.expected_columns, retrieved_column_ids)
    metric_recall_hit = score_recall(case.expected_metrics, retrieved_metric_ids)
    value_recall_hit = score_recall(case.expected_values, retrieved_value_ids)

    return QueryEvalResult(
        case_id=case.case_id,
        question=case.question,
        generated_sql=generated_sql,
        reference_sql=case.reference_sql,
        execution_success=execution_error is None and generated_result is not None,
        sql_correct=compare_result_values(
            generated_result,
            reference_result,
            order_sensitive=_is_order_sensitive_case(case.tags),
        ),
        strict_sql_correct=compare_results(
            generated_result,
            reference_result,
            order_sensitive=_is_order_sensitive_case(case.tags),
        ),
        alias_consistent=compare_column_names(
            generated_result,
            reference_result,
            order_sensitive=_is_order_sensitive_case(case.tags),
        ),
        generated_result=generated_result,
        reference_result=reference_result,
        retrieved_table_ids=retrieved_table_ids,
        retrieved_column_ids=retrieved_column_ids,
        retrieved_metric_ids=retrieved_metric_ids,
        retrieved_value_ids=retrieved_value_ids,
        table_recall_hit=table_recall_hit,
        column_recall_hit=column_recall_hit,
        metric_recall_hit=metric_recall_hit,
        value_recall_hit=value_recall_hit,
        full_recall_hit=(
            table_recall_hit
            and column_recall_hit
            and metric_recall_hit
            and value_recall_hit
        ),
        error_message=execution_error,
        tags=case.tags,
    )


def build_failed_eval_result(
    case: QueryEvalCase,
    error_message: str,
) -> QueryEvalResult:
    return QueryEvalResult(
        case_id=case.case_id,
        question=case.question,
        generated_sql=None,
        reference_sql=case.reference_sql,
        execution_success=False,
        sql_correct=False,
        strict_sql_correct=False,
        alias_consistent=False,
        generated_result=None,
        reference_result=[],
        retrieved_table_ids=[],
        retrieved_column_ids=[],
        retrieved_metric_ids=[],
        retrieved_value_ids=[],
        table_recall_hit=False,
        column_recall_hit=False,
        metric_recall_hit=False,
        value_recall_hit=False,
        full_recall_hit=False,
        error_message=error_message,
        tags=case.tags,
    )


async def run_eval_case(
    case: QueryEvalCase,
    context: DataAgentContext,
    dw_mysql_repository: DWMySQLRepository,
) -> QueryEvalResult:
    from app.agent.graph import graph

    final_state = await graph.ainvoke({"query": case.question}, context=context)
    reference_result = await dw_mysql_repository.run(case.reference_sql)
    return build_eval_result(case, final_state, reference_result)


async def evaluate_cases(cases: list[QueryEvalCase]) -> list[QueryEvalResult]:
    async with create_eval_runtime() as (context, dw_mysql_repository):
        results: list[QueryEvalResult] = []
        for case in cases:
            try:
                results.append(await run_eval_case(case, context, dw_mysql_repository))
            except Exception as exc:
                results.append(build_failed_eval_result(case, str(exc)))
        return results


def select_eval_cases(
    dataset_path: Path,
    case_id: str | None = None,
    tag: str | None = None,
) -> list[QueryEvalCase]:
    cases = load_eval_cases(dataset_path)
    if case_id is not None:
        cases = [case for case in cases if case.case_id == case_id]
    if tag is not None:
        cases = [case for case in cases if tag in case.tags]
    if not cases:
        raise ValueError("No evaluation cases selected with the provided filters.")
    return cases


def serialize_eval_results(results: list[QueryEvalResult]) -> str:
    return json.dumps(
        [asdict(result) for result in results],
        ensure_ascii=False,
        indent=2,
        default=str,
    )


def summarize_results(results: list[QueryEvalResult]) -> QueryEvalSummary:
    total = len(results)
    return QueryEvalSummary(
        total_cases=total,
        sql_accuracy=_rate(sum(result.sql_correct for result in results), total),
        strict_sql_accuracy=_rate(
            sum(result.strict_sql_correct for result in results), total
        ),
        alias_consistency_rate=_rate(
            sum(result.alias_consistent for result in results), total
        ),
        execution_success_rate=_rate(
            sum(result.execution_success for result in results), total
        ),
        table_recall_coverage=_rate(
            sum(result.table_recall_hit for result in results), total
        ),
        column_recall_coverage=_rate(
            sum(result.column_recall_hit for result in results), total
        ),
        metric_recall_coverage=_rate(
            sum(result.metric_recall_hit for result in results), total
        ),
        value_recall_coverage=_rate(
            sum(result.value_recall_hit for result in results), total
        ),
        full_recall_rate=_rate(
            sum(result.full_recall_hit for result in results), total
        ),
        by_tag=_build_tag_metrics(results),
    )


def render_summary_markdown(summary: QueryEvalSummary) -> str:
    lines = [
        "# 问数评测汇总",
        "",
        f"- 总样本数：{summary.total_cases}",
        f"- SQL 正确率（值正确）：{summary.sql_accuracy:.2%}",
        f"- 严格结果一致率：{summary.strict_sql_accuracy:.2%}",
        f"- 列别名一致率：{summary.alias_consistency_rate:.2%}",
        f"- 执行成功率：{summary.execution_success_rate:.2%}",
        f"- 表召回覆盖率：{summary.table_recall_coverage:.2%}",
        f"- 字段召回覆盖率：{summary.column_recall_coverage:.2%}",
        f"- 指标召回覆盖率：{summary.metric_recall_coverage:.2%}",
        f"- 取值召回覆盖率：{summary.value_recall_coverage:.2%}",
        f"- 问题级全量召回率：{summary.full_recall_rate:.2%}",
        "",
        "| 标签 | SQL 正确率 | 严格结果一致率 | 列别名一致率 | 执行成功率 | 表召回覆盖率 | 字段召回覆盖率 | 指标召回覆盖率 | 取值召回覆盖率 | 全量召回率 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for tag, metrics in sorted(summary.by_tag.items()):
        lines.append(
            f"| {tag} | {metrics['sql_accuracy']:.2%} | "
            f"{metrics['strict_sql_accuracy']:.2%} | "
            f"{metrics['alias_consistency_rate']:.2%} | "
            f"{metrics['execution_success_rate']:.2%} | "
            f"{metrics['table_recall_coverage']:.2%} | "
            f"{metrics['column_recall_coverage']:.2%} | "
            f"{metrics['metric_recall_coverage']:.2%} | "
            f"{metrics['value_recall_coverage']:.2%} | "
            f"{metrics['full_recall_rate']:.2%} |"
        )
    return "\n".join(lines)


def write_report_files(
    output_dir: Path,
    summary: QueryEvalSummary,
    results: list[QueryEvalResult],
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)

    summary_json_path = output_dir / "summary.json"
    summary_markdown_path = output_dir / "summary.md"
    details_json_path = output_dir / "details.json"

    summary_json_path.write_text(
        json.dumps(asdict(summary), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    summary_markdown_path.write_text(
        render_summary_markdown(summary),
        encoding="utf-8",
    )
    details_json_path.write_text(
        serialize_eval_results(results),
        encoding="utf-8",
    )

    return {
        "summary_json": summary_json_path,
        "summary_markdown": summary_markdown_path,
        "details_json": details_json_path,
    }


@asynccontextmanager
async def create_eval_runtime():
    closers: list[tuple[object, str]] = []

    try:
        meta_mysql_client_manager.init()
        closers.append((meta_mysql_client_manager, "engine"))
        dw_mysql_client_manager.init()
        closers.append((dw_mysql_client_manager, "engine"))
        qdrant_client_manager.init()
        closers.append((qdrant_client_manager, "client"))
        embedding_client_manager.init()
        es_client_manager.init()
        closers.append((es_client_manager, "client"))

        from app.repositories.es.value_es_repository import ValueESRepository
        from app.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository
        from app.repositories.mysql.meta.meta_mysql_repository import (
            MetaMySQLRepository,
        )
        from app.repositories.qdrant.column_qdrant_repository import (
            ColumnQdrantRepository,
        )
        from app.repositories.qdrant.metric_qdrant_repository import (
            MetricQdrantRepository,
        )

        async with (
            meta_mysql_client_manager.session_factory() as meta_session,
            dw_mysql_client_manager.session_factory() as dw_session,
        ):
            meta_mysql_repository = MetaMySQLRepository(meta_session)
            dw_mysql_repository = DWMySQLRepository(dw_session)
            context: DataAgentContext = {
                "column_qdrant_repository": ColumnQdrantRepository(
                    qdrant_client_manager.client
                ),
                "embedding_client": embedding_client_manager.client,
                "metric_qdrant_repository": MetricQdrantRepository(
                    qdrant_client_manager.client
                ),
                "value_es_repository": ValueESRepository(es_client_manager.client),
                "meta_mysql_repository": meta_mysql_repository,
                "dw_mysql_repository": dw_mysql_repository,
            }
            yield context, dw_mysql_repository
    finally:
        for manager, attr_name in reversed(closers):
            if getattr(manager, attr_name, None) is not None:
                await manager.close()


def _extract_ids(items: list[Any]) -> list[str]:
    ids: list[str] = []
    for item in items:
        if isinstance(item, dict):
            item_id = item.get("id")
        else:
            item_id = getattr(item, "id", None)
        if isinstance(item_id, str):
            ids.append(item_id)
    return ids


def _extract_table_ids(final_state: dict[str, Any]) -> list[str]:
    table_ids: list[str] = []
    seen: set[str] = set()

    for item in final_state.get("retrieved_column_infos", []):
        table_id = (
            item.get("table_id")
            if isinstance(item, dict)
            else getattr(item, "table_id", None)
        )
        if isinstance(table_id, str) and table_id not in seen:
            seen.add(table_id)
            table_ids.append(table_id)

    for item in final_state.get("retrieved_metric_infos", []):
        relevant_columns = (
            item.get("relevant_columns", [])
            if isinstance(item, dict)
            else getattr(item, "relevant_columns", [])
        )
        for column_id in relevant_columns:
            if isinstance(column_id, str) and "." in column_id:
                table_id = column_id.rsplit(".", 1)[0]
                if table_id not in seen:
                    seen.add(table_id)
                    table_ids.append(table_id)

    for item in final_state.get("retrieved_value_infos", []):
        column_id = (
            item.get("column_id")
            if isinstance(item, dict)
            else getattr(item, "column_id", None)
        )
        if isinstance(column_id, str) and "." in column_id:
            table_id = column_id.rsplit(".", 1)[0]
            if table_id not in seen:
                seen.add(table_id)
                table_ids.append(table_id)

    return table_ids


def _build_tag_metrics(results: list[QueryEvalResult]) -> dict[str, dict[str, float]]:
    metrics_by_tag: dict[str, dict[str, float]] = {}
    tags = sorted({tag for result in results for tag in result.tags})
    for tag in tags:
        tag_results = [result for result in results if tag in result.tags]
        total = len(tag_results)
        metrics_by_tag[tag] = {
            "sql_accuracy": _rate(
                sum(result.sql_correct for result in tag_results), total
            ),
            "strict_sql_accuracy": _rate(
                sum(result.strict_sql_correct for result in tag_results), total
            ),
            "alias_consistency_rate": _rate(
                sum(result.alias_consistent for result in tag_results), total
            ),
            "execution_success_rate": _rate(
                sum(result.execution_success for result in tag_results), total
            ),
            "table_recall_coverage": _rate(
                sum(result.table_recall_hit for result in tag_results), total
            ),
            "column_recall_coverage": _rate(
                sum(result.column_recall_hit for result in tag_results), total
            ),
            "metric_recall_coverage": _rate(
                sum(result.metric_recall_hit for result in tag_results), total
            ),
            "value_recall_coverage": _rate(
                sum(result.value_recall_hit for result in tag_results), total
            ),
            "full_recall_rate": _rate(
                sum(result.full_recall_hit for result in tag_results), total
            ),
        }
    return metrics_by_tag


def _rate(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _is_order_sensitive_case(tags: list[str]) -> bool:
    return "topn" in tags
