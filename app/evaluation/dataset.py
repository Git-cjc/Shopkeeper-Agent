from pathlib import Path

import yaml

from app.evaluation.models import QueryEvalCase


def load_eval_cases(path: Path) -> list[QueryEvalCase]:
    raw_data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw_cases = raw_data.get("cases", [])

    return [
        QueryEvalCase(
            case_id=raw_case["case_id"],
            question=raw_case["question"],
            reference_sql=raw_case["reference_sql"],
            expected_tables=_read_list_field(raw_case, "expected_tables"),
            expected_columns=_read_list_field(raw_case, "expected_columns"),
            expected_metrics=_read_list_field(raw_case, "expected_metrics"),
            expected_values=_read_list_field(raw_case, "expected_values"),
            tags=_read_list_field(raw_case, "tags"),
        )
        for raw_case in raw_cases
    ]


def _read_list_field(raw_case: dict, field_name: str) -> list[str]:
    value = raw_case.get(field_name, [])
    if not isinstance(value, list):
        case_id = raw_case.get("case_id", "<unknown>")
        raise ValueError(
            f"Case {case_id} field '{field_name}' must be a list, got "
            f"{type(value).__name__}."
        )

    return value
