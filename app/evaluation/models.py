from dataclasses import dataclass, field


@dataclass(slots=True)
class QueryEvalCase:
    case_id: str
    question: str
    reference_sql: str
    expected_tables: list[str] = field(default_factory=list)
    expected_columns: list[str] = field(default_factory=list)
    expected_metrics: list[str] = field(default_factory=list)
    expected_values: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
