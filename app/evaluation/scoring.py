from collections.abc import Sequence
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

    return _normalize_values(generated, order_sensitive=order_sensitive) == _normalize_values(
        reference, order_sensitive=order_sensitive
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
