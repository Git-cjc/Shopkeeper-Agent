from collections.abc import Sequence
from itertools import combinations
from typing import Any


def compare_results(
    generated: Any,
    reference: Any,
    *,
    order_sensitive: bool = False,
) -> bool:
    if generated is None or reference is None:
        return False

    return _normalize_result(generated, order_sensitive=order_sensitive) == _normalize_result(
        reference, order_sensitive=order_sensitive
    )


def compare_result_values(
    generated: Any,
    reference: Any,
    *,
    order_sensitive: bool = False,
) -> bool:
    if generated is None or reference is None:
        return False

    return _projectable_normalize_values(
        generated, reference, order_sensitive=order_sensitive
    ) == _projectable_normalize_values(
        reference, generated, order_sensitive=order_sensitive
    )


def compare_column_names(
    generated: Any,
    reference: Any,
    *,
    order_sensitive: bool = False,
) -> bool:
    if generated is None or reference is None:
        return False

    return _normalize_column_names(
        generated, order_sensitive=order_sensitive
    ) == _normalize_column_names(reference, order_sensitive=order_sensitive)


def score_recall(expected_ids: list[str], actual_ids: list[str]) -> bool:
    return set(expected_ids).issubset(set(actual_ids))


def _normalize_result(value: Any, *, order_sensitive: bool) -> Any:
    if isinstance(value, dict):
        return {
            str(key).lower(): _normalize_result(
                value[key], order_sensitive=order_sensitive
            )
            for key in sorted(value, key=lambda item: str(item).lower())
        }

    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        normalized_items = [
            _normalize_result(item, order_sensitive=order_sensitive) for item in value
        ]
        if order_sensitive:
            return normalized_items
        return sorted(normalized_items, key=_sort_key)

    return value


def _sort_key(value: Any) -> str:
    return repr(value)


def _normalize_values(value: Any, *, order_sensitive: bool) -> Any:
    if isinstance(value, dict):
        return [
            _normalize_values(item, order_sensitive=order_sensitive)
            for item in value.values()
        ]

    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        normalized_items = [
            _normalize_values(item, order_sensitive=order_sensitive) for item in value
        ]
        if order_sensitive:
            return normalized_items
        return sorted(normalized_items, key=_sort_key)

    return value


def _projectable_normalize_values(
    primary: Any,
    other: Any,
    *,
    order_sensitive: bool,
) -> Any:
    normalized_primary = _normalize_values(primary, order_sensitive=order_sensitive)
    normalized_other = _normalize_values(other, order_sensitive=order_sensitive)

    if (
        isinstance(normalized_primary, list)
        and isinstance(normalized_other, list)
        and normalized_primary
        and normalized_other
        and all(isinstance(row, list) for row in normalized_primary)
        and all(isinstance(row, list) for row in normalized_other)
    ):
        primary_width = len(normalized_primary[0])
        other_width = len(normalized_other[0])
        if primary_width > other_width:
            for indexes in combinations(range(primary_width), other_width):
                projected = [
                    [row[index] for index in indexes] for row in normalized_primary
                ]
                candidate = (
                    projected
                    if order_sensitive
                    else sorted(projected, key=_sort_key)
                )
                if candidate == normalized_other:
                    return candidate

    return normalized_primary


def _normalize_column_names(value: Any, *, order_sensitive: bool) -> Any:
    if isinstance(value, dict):
        return [
            str(key).lower()
            for key in sorted(value, key=lambda item: str(item).lower())
        ]

    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        normalized_items = [
            _normalize_column_names(item, order_sensitive=order_sensitive)
            for item in value
        ]
        if order_sensitive:
            return normalized_items
        return sorted(normalized_items, key=_sort_key)

    return value
