from pathlib import Path

import pytest

from app.evaluation.dataset import load_eval_cases


def test_load_eval_cases_reads_yaml_dataset() -> None:
    dataset_path = Path("app/evaluation/datasets/query_eval_set.yaml")

    cases = load_eval_cases(dataset_path)

    assert len(cases) == 20
    assert cases[0].case_id == "q001_total_gmv"
    assert cases[0].question == "总GMV是多少？"
    assert cases[0].expected_tables == ["fact_order"]
    assert cases[0].expected_columns == ["fact_order.order_amount"]
    assert cases[0].expected_metrics == ["GMV"]
    assert cases[0].expected_values == []
    assert "aggregate" in cases[0].tags


def test_load_eval_cases_maps_filter_and_time_fields() -> None:
    dataset_path = Path("app/evaluation/datasets/query_eval_set.yaml")

    cases = load_eval_cases(dataset_path)
    target_case = next(case for case in cases if case.case_id == "q010_gmv_q1_by_region")

    assert target_case.expected_tables == ["fact_order", "dim_date", "dim_region"]
    assert target_case.expected_columns == [
        "fact_order.order_amount",
        "dim_date.quarter",
        "dim_region.region_name",
    ]
    assert target_case.expected_metrics == ["GMV"]
    assert target_case.expected_values == ["dim_date.quarter.Q1"]
    assert "group_by" in target_case.tags
    assert "time" in target_case.tags


def test_load_eval_cases_raises_when_list_field_is_not_a_list(tmp_path: Path) -> None:
    dataset_path = tmp_path / "invalid_eval_set.yaml"
    dataset_path.write_text(
        """
cases:
  - case_id: invalid_case
    question: 错误样本
    reference_sql: SELECT 1;
    expected_tables: fact_order
    expected_columns: []
    expected_metrics: []
    expected_values: []
    tags: []
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="expected_tables.*list"):
        load_eval_cases(dataset_path)
