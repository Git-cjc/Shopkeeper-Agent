from app.evaluation.scoring import (
    compare_column_names,
    compare_result_values,
    compare_results,
    score_recall,
)


def test_compare_results_ignores_row_order_by_default() -> None:
    reference = [
        {"region_name": "华东", "gmv": 1000.0},
        {"region_name": "华南", "gmv": 800.0},
    ]
    generated = [
        {"region_name": "华南", "gmv": 800.0},
        {"region_name": "华东", "gmv": 1000.0},
    ]

    assert compare_results(generated, reference) is True


def test_compare_results_can_require_row_order() -> None:
    reference = [
        {"brand": "苹果", "gmv": 1000.0},
        {"brand": "华为", "gmv": 900.0},
    ]
    generated = [
        {"brand": "华为", "gmv": 900.0},
        {"brand": "苹果", "gmv": 1000.0},
    ]

    assert compare_results(generated, reference, order_sensitive=True) is False


def test_compare_results_ignores_column_order() -> None:
    reference = [{"region_name": "华东", "gmv": 1000.0}]
    generated = [{"gmv": 1000.0, "region_name": "华东"}]

    assert compare_results(generated, reference) is True


def test_compare_results_ignores_column_name_case() -> None:
    reference = [{"GMV": 1000.0, "Region_Name": "华东"}]
    generated = [{"gmv": 1000.0, "region_name": "华东"}]

    assert compare_results(generated, reference) is True


def test_compare_result_values_ignores_column_names() -> None:
    reference = [{"总销量": 1000.0, "地区": "华东"}]
    generated = [{"total_quantity": 1000.0, "region_name": "华东"}]

    assert compare_result_values(generated, reference) is True


def test_compare_result_values_preserves_select_column_order() -> None:
    reference = [{"brand": "华为", "gmv": 27996.0}]
    generated = [{"品牌": "华为", "GMV": 27996.0}]

    assert compare_result_values(generated, reference) is True


def test_compare_result_values_allows_redundant_filtered_dimension_column() -> None:
    reference = [
        {"brand": "华为", "gmv": 27996.0},
        {"brand": "雀巢", "gmv": 650.0},
    ]
    generated = [
        {"地区": "华东", "品牌": "华为", "GMV": 27996.0},
        {"地区": "华东", "品牌": "雀巢", "GMV": 650.0},
    ]

    assert compare_result_values(generated, reference) is True


def test_compare_column_names_detects_alias_mismatch() -> None:
    reference = [{"总销量": 1000.0, "地区": "华东"}]
    generated = [{"total_quantity": 1000.0, "region_name": "华东"}]

    assert compare_column_names(generated, reference) is False


def test_compare_results_returns_false_when_none_present() -> None:
    assert compare_results(None, [{"gmv": 1000.0}]) is False
    assert compare_results([{"gmv": 1000.0}], None) is False


def test_score_recall_requires_expected_ids_to_be_subset_of_actual() -> None:
    assert score_recall(["GMV", "fact_order.order_amount"], ["GMV", "fact_order.order_amount", "dim_region.region_name"]) is True
    assert score_recall(["GMV", "dim_region.region_name"], ["GMV"]) is False
