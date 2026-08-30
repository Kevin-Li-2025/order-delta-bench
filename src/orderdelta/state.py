from __future__ import annotations

import copy
import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

ITEM_FIELDS = (
    "sku",
    "quantity",
    "size",
    "add",
    "remove",
    "special_instructions",
)
CONSTRAINT_FIELDS = ("allergens", "dietary")


class StateError(ValueError):
    """Raised when a cart cannot be represented as an identity-bearing state."""


@dataclass(frozen=True)
class DiffScore:
    precision: float
    recall: float
    correct: int
    actual: int
    expected: int
    unexpected: list[dict[str, Any]]
    missing: list[dict[str, Any]]


def pointer_escape(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def pointer_unescape(value: str) -> str:
    return value.replace("~1", "/").replace("~0", "~")


def _normalized_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted(str(item) for item in value)


def normalized_item(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "sku": row.get("sku"),
        "quantity": row.get("quantity"),
        "size": row.get("size"),
        "add": _normalized_list(row.get("add")),
        "remove": _normalized_list(row.get("remove")),
        "special_instructions": row.get("special_instructions", ""),
    }


def normalized_constraints(order: dict[str, Any]) -> dict[str, list[str]]:
    constraints = order.get("constraints")
    if not isinstance(constraints, dict):
        constraints = {}
    return {
        "allergens": _normalized_list(constraints.get("allergens")),
        "dietary": _normalized_list(constraints.get("dietary")),
    }


def line_map(order: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(order, dict) or not isinstance(order.get("items"), list):
        raise StateError("order_items_not_list")
    lines: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(order["items"]):
        if not isinstance(row, dict):
            raise StateError(f"line_{index}_not_object")
        line_id = row.get("line_id")
        if not isinstance(line_id, str) or not line_id:
            raise StateError(f"line_{index}_missing_identity")
        if line_id in lines:
            raise StateError(f"duplicate_line_id:{line_id}")
        lines[line_id] = normalized_item(row)
    return lines


def order_to_state(order: dict[str, Any], version: int = 1) -> dict[str, Any]:
    return {
        "version": version,
        "lines": line_map(order),
        "constraints": normalized_constraints(order),
    }


def state_to_order(state: dict[str, Any]) -> dict[str, Any]:
    lines = state.get("lines")
    if not isinstance(lines, dict):
        raise StateError("state_lines_not_object")
    items = []
    for line_id, value in lines.items():
        if not isinstance(line_id, str) or not isinstance(value, dict):
            raise StateError("state_line_invalid")
        items.append({"line_id": line_id, **copy.deepcopy(value)})
    return {
        "items": items,
        "constraints": copy.deepcopy(state.get("constraints", {})),
    }


def identity_orders_equal(left: dict[str, Any] | None, right: dict[str, Any] | None) -> bool:
    try:
        return line_map(left) == line_map(right) and normalized_constraints(left or {}) == normalized_constraints(right or {})
    except StateError:
        return False


def state_diff(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    before_lines = line_map(before)
    after_lines = line_map(after)
    entries: list[dict[str, Any]] = []

    for line_id in sorted(before_lines.keys() - after_lines.keys()):
        entries.append({
            "path": f"/lines/{pointer_escape(line_id)}",
            "op": "remove",
            "before": before_lines[line_id],
            "after": None,
        })
    for line_id in sorted(after_lines.keys() - before_lines.keys()):
        entries.append({
            "path": f"/lines/{pointer_escape(line_id)}",
            "op": "add",
            "before": None,
            "after": after_lines[line_id],
        })
    for line_id in sorted(before_lines.keys() & after_lines.keys()):
        for field in ITEM_FIELDS:
            before_value = before_lines[line_id].get(field)
            after_value = after_lines[line_id].get(field)
            if before_value != after_value:
                entries.append({
                    "path": f"/lines/{pointer_escape(line_id)}/{pointer_escape(field)}",
                    "op": "replace",
                    "before": before_value,
                    "after": after_value,
                })

    before_constraints = normalized_constraints(before)
    after_constraints = normalized_constraints(after)
    for field in CONSTRAINT_FIELDS:
        if before_constraints[field] != after_constraints[field]:
            entries.append({
                "path": f"/constraints/{field}",
                "op": "replace",
                "before": before_constraints[field],
                "after": after_constraints[field],
            })
    return entries


def _diff_identity(entry: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(entry.get("path")),
        str(entry.get("op")),
        json.dumps(entry.get("after"), sort_keys=True, separators=(",", ":")),
    )


def score_diff(expected: Iterable[dict[str, Any]], actual: Iterable[dict[str, Any]]) -> DiffScore:
    expected_list = list(expected)
    actual_list = list(actual)
    expected_keys = {_diff_identity(entry) for entry in expected_list}
    actual_keys = {_diff_identity(entry) for entry in actual_list}
    correct_keys = expected_keys & actual_keys
    precision = len(correct_keys) / len(actual_keys) if actual_keys else (1.0 if not expected_keys else 0.0)
    recall = len(correct_keys) / len(expected_keys) if expected_keys else (1.0 if not actual_keys else 0.0)
    return DiffScore(
        precision=precision,
        recall=recall,
        correct=len(correct_keys),
        actual=len(actual_keys),
        expected=len(expected_keys),
        unexpected=[entry for entry in actual_list if _diff_identity(entry) not in expected_keys],
        missing=[entry for entry in expected_list if _diff_identity(entry) not in actual_keys],
    )


def diff_touches_path(diff: Iterable[dict[str, Any]], protected_path: str) -> bool:
    prefix = protected_path.rstrip("/")
    return any(
        str(entry.get("path")) == prefix or str(entry.get("path", "")).startswith(prefix + "/")
        for entry in diff
    )


def protected_paths_for_case(case: dict[str, Any]) -> list[str]:
    paths = [f"/lines/{pointer_escape(str(line_id))}" for line_id in case.get("unchanged_line_ids", [])]
    expected_paths = {str(entry.get("path")) for entry in case.get("expected_writes", []) if isinstance(entry, dict)}
    if not any(path.startswith("/constraints/") for path in expected_paths):
        paths.append("/constraints")
    return sorted(set(paths))
