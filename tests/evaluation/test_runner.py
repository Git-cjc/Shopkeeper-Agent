from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.entities.column_info import ColumnInfo
from app.entities.metric_info import MetricInfo
from app.entities.value_info import ValueInfo
from app.evaluation.models import QueryEvalCase
from app.evaluation import runner
from app.evaluation.runner import (
    QueryEvalResult,
    build_eval_result,
    render_summary_markdown,
    select_eval_cases,
    summarize_results,
    write_report_files,
)


def test_build_eval_result_collects_sql_execution_and_recall() -> None:
    case = QueryEvalCase(
        case_id="case_001",
        question="统计华北地区销售总额",
        reference_sql="select 1 as gmv",
        expected_tables=["fact_order"],
        expected_columns=["fact_order.order_amount"],
        expected_metrics=["GMV"],
        expected_values=["dim_region.region_name.华北"],
        tags=["smoke"],
    )

    final_state = {
        "sql": "select 1 as gmv",
        "execution_result": [{"gmv": 1}],
        "execution_error": None,
        "retrieved_column_infos": [
            ColumnInfo(
                id="fact_order.order_amount",
                name="order_amount",
                type="float",
                role="measure",
                examples=[],
                description="订单金额",
                alias=["销售额"],
                table_id="fact_order",
            )
        ],
        "retrieved_metric_infos": [
            MetricInfo(
                id="GMV",
                name="GMV",
                description="成交总额",
                relevant_columns=["fact_order.order_amount"],
                alias=["成交总额"],
            )
        ],
        "retrieved_value_infos": [
            ValueInfo(
                id="dim_region.region_name.华北",
                value="华北",
                column_id="dim_region.region_name",
            )
        ],
    }

    result = build_eval_result(case, final_state, [{"gmv": 1}])

    assert result.case_id == "case_001"
    assert result.generated_sql == "select 1 as gmv"
    assert result.execution_success is True
    assert result.sql_correct is True
    assert result.strict_sql_correct is True
    assert result.alias_consistent is True
    assert result.retrieved_table_ids == ["fact_order", "dim_region"]
    assert result.table_recall_hit is True
    assert result.retrieved_column_ids == ["fact_order.order_amount"]
    assert result.retrieved_metric_ids == ["GMV"]
    assert result.retrieved_value_ids == ["dim_region.region_name.华北"]
    assert result.full_recall_hit is True


def test_build_eval_result_handles_dict_payloads_and_partial_recall() -> None:
    case = QueryEvalCase(
        case_id="case_002",
        question="统计华东地区销售总额",
        reference_sql="select 2 as gmv",
        expected_tables=["fact_order", "dim_region"],
        expected_columns=["fact_order.order_amount"],
        expected_metrics=["GMV"],
        expected_values=["dim_region.region_name.华东"],
        tags=["smoke"],
    )

    final_state = {
        "sql": "select 1 as total_quantity",
        "execution_result": [{"total_quantity": 1}],
        "execution_error": None,
        "retrieved_column_infos": [{"id": "fact_order.order_amount"}],
        "retrieved_metric_infos": [{"id": "GMV"}],
        "retrieved_value_infos": [],
    }

    result = build_eval_result(case, final_state, [{"gmv": 1}])

    assert result.execution_success is True
    assert result.sql_correct is True
    assert result.strict_sql_correct is False
    assert result.alias_consistent is False
    assert result.table_recall_hit is False
    assert result.column_recall_hit is True
    assert result.metric_recall_hit is True
    assert result.value_recall_hit is False
    assert result.full_recall_hit is False
    assert result.error_message is None


def test_select_eval_cases_raises_when_filters_match_nothing(tmp_path: Path) -> None:
    dataset_path = tmp_path / "eval_cases.yaml"
    dataset_path.write_text(
        """
cases:
  - case_id: case_001
    question: 统计华北地区销售总额
    reference_sql: SELECT 1;
    expected_tables: []
    expected_columns: []
    expected_metrics: []
    expected_values: []
    tags: [region]
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="No evaluation cases selected"):
        select_eval_cases(dataset_path, case_id="missing")


@pytest.mark.asyncio
async def test_evaluate_cases_keeps_batch_running_when_single_case_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_case = QueryEvalCase(
        case_id="case_001",
        question="q1",
        reference_sql="select 1",
    )
    second_case = QueryEvalCase(
        case_id="case_002",
        question="q2",
        reference_sql="select 2",
    )

    async def fake_run_eval_case(
        case: QueryEvalCase,
        context: object,
        dw_mysql_repository: object,
    ):
        if case.case_id == "case_001":
            raise RuntimeError("graph failed")
        return SimpleNamespace(case_id="case_002", error_message=None)

    class FakeRuntime:
        async def __aenter__(self):
            return object(), object()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(runner, "run_eval_case", fake_run_eval_case)
    monkeypatch.setattr(runner, "create_eval_runtime", lambda: FakeRuntime())

    results = await runner.evaluate_cases([first_case, second_case])

    assert [result.case_id for result in results] == ["case_001", "case_002"]
    assert results[0].execution_success is False
    assert results[0].error_message == "graph failed"
    assert results[1].case_id == "case_002"


@pytest.mark.asyncio
async def test_create_eval_runtime_preserves_original_init_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    meta_close = AsyncMock()
    dw_close = AsyncMock()
    qdrant_close = AsyncMock()
    es_close = AsyncMock()

    def fake_meta_init() -> None:
        runner.meta_mysql_client_manager.engine = object()

    monkeypatch.setattr(runner.meta_mysql_client_manager, "init", fake_meta_init)
    monkeypatch.setattr(
        runner.meta_mysql_client_manager, "close", meta_close
    )
    monkeypatch.setattr(
        runner.dw_mysql_client_manager,
        "init",
        lambda: (_ for _ in ()).throw(RuntimeError("dw init failed")),
    )
    monkeypatch.setattr(runner.dw_mysql_client_manager, "close", dw_close)
    monkeypatch.setattr(runner.qdrant_client_manager, "close", qdrant_close)
    monkeypatch.setattr(runner.es_client_manager, "close", es_close)

    with pytest.raises(RuntimeError, match="dw init failed"):
        async with runner.create_eval_runtime():
            pass

    meta_close.assert_awaited_once()
    dw_close.assert_not_awaited()
    qdrant_close.assert_not_awaited()
    es_close.assert_not_awaited()


def test_summarize_results_computes_global_and_tag_metrics() -> None:
    results = [
        QueryEvalResult(
            case_id="case_001",
            question="q1",
            generated_sql="select 1",
            reference_sql="select 1",
            execution_success=True,
            sql_correct=True,
            strict_sql_correct=True,
            alias_consistent=True,
            generated_result=[{"v": 1}],
            reference_result=[{"v": 1}],
            retrieved_table_ids=["t1"],
            retrieved_column_ids=["c1"],
            retrieved_metric_ids=["m1"],
            retrieved_value_ids=["v1"],
            table_recall_hit=True,
            column_recall_hit=True,
            metric_recall_hit=True,
            value_recall_hit=True,
            full_recall_hit=True,
            error_message=None,
            tags=["smoke"],
        ),
        QueryEvalResult(
            case_id="case_002",
            question="q2",
            generated_sql="select 2",
            reference_sql="select 2",
            execution_success=False,
            sql_correct=True,
            strict_sql_correct=False,
            alias_consistent=False,
            generated_result=None,
            reference_result=[{"v": 2}],
            retrieved_table_ids=["t2"],
            retrieved_column_ids=["c2"],
            retrieved_metric_ids=[],
            retrieved_value_ids=[],
            table_recall_hit=False,
            column_recall_hit=True,
            metric_recall_hit=False,
            value_recall_hit=False,
            full_recall_hit=False,
            error_message="boom",
            tags=["smoke", "failure"],
        ),
    ]

    summary = summarize_results(results)

    assert summary.total_cases == 2
    assert summary.sql_accuracy == 1.0
    assert summary.strict_sql_accuracy == 0.5
    assert summary.alias_consistency_rate == 0.5
    assert summary.execution_success_rate == 0.5
    assert summary.table_recall_coverage == 0.5
    assert summary.column_recall_coverage == 1.0
    assert summary.metric_recall_coverage == 0.5
    assert summary.value_recall_coverage == 0.5
    assert summary.full_recall_rate == 0.5
    assert summary.by_tag["smoke"]["sql_accuracy"] == 1.0
    assert summary.by_tag["smoke"]["strict_sql_accuracy"] == 0.5
    assert summary.by_tag["failure"]["execution_success_rate"] == 0.0


def test_write_report_files_persists_summary_and_details(tmp_path: Path) -> None:
    results = [
        QueryEvalResult(
            case_id="case_001",
            question="q1",
            generated_sql="select 1",
            reference_sql="select 1",
            execution_success=True,
            sql_correct=True,
            strict_sql_correct=True,
            alias_consistent=True,
            generated_result=[{"v": 1}],
            reference_result=[{"v": 1}],
            retrieved_table_ids=["t1"],
            retrieved_column_ids=["c1"],
            retrieved_metric_ids=["m1"],
            retrieved_value_ids=["v1"],
            table_recall_hit=True,
            column_recall_hit=True,
            metric_recall_hit=True,
            value_recall_hit=True,
            full_recall_hit=True,
            error_message=None,
            tags=["smoke"],
        )
    ]

    summary = summarize_results(results)
    paths = write_report_files(tmp_path, summary, results)
    summary_markdown = render_summary_markdown(summary)

    assert paths["summary_json"] == tmp_path / "summary.json"
    assert paths["summary_markdown"] == tmp_path / "summary.md"
    assert paths["details_json"] == tmp_path / "details.json"
    assert paths["summary_json"].exists()
    assert paths["summary_markdown"].exists()
    assert paths["details_json"].exists()
    assert "# 问数评测汇总" in summary_markdown
    assert "总样本数：1" in summary_markdown
    assert "SQL 正确率（值正确）：100.00%" in summary_markdown
    assert "严格结果一致率：100.00%" in summary_markdown
    assert "列别名一致率：100.00%" in summary_markdown
    assert "执行成功率：100.00%" in summary_markdown
    assert "表召回覆盖率：100.00%" in summary_markdown
    assert "| smoke | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% |" in summary_markdown
    assert paths["summary_markdown"].read_text(encoding="utf-8") == summary_markdown
    assert "case_001" in paths["details_json"].read_text(encoding="utf-8")
