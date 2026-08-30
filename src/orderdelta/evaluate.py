from __future__ import annotations

import copy
import json
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

from src.orderbench.contracts import MENU

from .contracts import STATUS_VALUES
from .state import (
    StateError,
    diff_touches_path,
    identity_orders_equal,
    line_map,
    order_to_state,
    pointer_unescape,
    protected_paths_for_case,
    score_diff,
    state_diff,
    state_to_order,
)

JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


@dataclass
class Evaluation:
    json_valid: bool
    schema_valid: bool
    status_correct: bool
    order_exact: bool
    constraints_exact: bool
    state_preserved_when_blocked: bool
    semantic_ok: bool
    unsafe_state_change: bool
    unintended_drift: bool
    identity_error: bool
    identity_observable: bool
    identity_fidelity: bool | None
    operation_executable: bool
    authorized_write_precision: float | None
    authorized_write_recall: float | None
    collateral_write_count: int | None
    actual_state_diff: list[dict[str, Any]] | None
    unexpected_state_diff: list[dict[str, Any]] | None
    missing_expected_state_diff: list[dict[str, Any]] | None
    error: str | None
    parsed: dict[str, Any] | None
    applied_order: dict[str, Any] | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "json_valid": self.json_valid,
            "schema_valid": self.schema_valid,
            "status_correct": self.status_correct,
            "order_exact": self.order_exact,
            "constraints_exact": self.constraints_exact,
            "state_preserved_when_blocked": self.state_preserved_when_blocked,
            "semantic_ok": self.semantic_ok,
            "unsafe_state_change": self.unsafe_state_change,
            "unintended_drift": self.unintended_drift,
            "identity_error": self.identity_error,
            "identity_observable": self.identity_observable,
            "identity_fidelity": self.identity_fidelity,
            "operation_executable": self.operation_executable,
            "authorized_write_precision": self.authorized_write_precision,
            "authorized_write_recall": self.authorized_write_recall,
            "collateral_write_count": self.collateral_write_count,
            "actual_state_diff": self.actual_state_diff,
            "unexpected_state_diff": self.unexpected_state_diff,
            "missing_expected_state_diff": self.missing_expected_state_diff,
            "error": self.error,
            "parsed": self.parsed,
            "applied_order": self.applied_order,
        }


def extract_json(text: str) -> tuple[dict[str, Any] | None, str | None]:
    stripped = text.strip()
    fence = JSON_FENCE.search(stripped)
    if fence:
        stripped = fence.group(1).strip()
    try:
        value = json.loads(stripped)
        if isinstance(value, dict):
            return value, None
        return None, "top_level_not_object"
    except json.JSONDecodeError:
        pass

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        try:
            value = json.loads(stripped[start : end + 1])
            if isinstance(value, dict):
                return value, None
            return None, "top_level_not_object"
        except json.JSONDecodeError as exc:
            return None, f"json_decode:{exc.msg}"
    return None, "no_json_object"


def strip_line_ids(order: dict[str, Any]) -> dict[str, Any]:
    return {
        "items": [
            {key: value for key, value in row.items() if key != "line_id"}
            for row in order.get("items", [])
            if isinstance(row, dict)
        ],
        "constraints": copy.deepcopy(order.get("constraints", {"allergens": [], "dietary": []})),
    }


def constraints_tuple(order: dict[str, Any] | None) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if not isinstance(order, dict) or not isinstance(order.get("constraints"), dict):
        return (), ()
    constraints = order["constraints"]
    allergens = constraints.get("allergens", [])
    dietary = constraints.get("dietary", [])
    if not isinstance(allergens, list):
        allergens = []
    if not isinstance(dietary, list):
        dietary = []
    return tuple(sorted(str(x) for x in allergens)), tuple(sorted(str(x) for x in dietary))


def canonical_item(row: dict[str, Any]) -> tuple:
    return (
        row.get("sku"),
        int(row.get("quantity", -1)) if isinstance(row.get("quantity"), int) else row.get("quantity"),
        row.get("size"),
        tuple(sorted(row.get("add", []) if isinstance(row.get("add"), list) else [])),
        tuple(sorted(row.get("remove", []) if isinstance(row.get("remove"), list) else [])),
        row.get("special_instructions", ""),
    )


def valid_quantity(value: Any) -> bool:
    """Match JSON Schema integer semantics and the public 1..20 contract."""
    return type(value) is int and 1 <= value <= 20


def item_counter(order: dict[str, Any] | None) -> Counter:
    if not isinstance(order, dict) or not isinstance(order.get("items"), list):
        return Counter()
    return Counter(canonical_item(row) for row in order["items"] if isinstance(row, dict))


def orders_equal(left: dict[str, Any] | None, right: dict[str, Any] | None) -> bool:
    return item_counter(left) == item_counter(right) and constraints_tuple(left) == constraints_tuple(right)


def item_schema_errors(row: Any, prefix: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(row, dict):
        return [f"{prefix}_not_object"]
    required = {"sku", "quantity", "size", "add", "remove", "special_instructions"}
    if set(row) - required:
        errors.append(f"{prefix}_extra_keys")
    if required - set(row):
        errors.append(f"{prefix}_missing_keys")
    if not isinstance(row.get("sku"), str):
        errors.append(f"{prefix}_bad_sku")
    if not valid_quantity(row.get("quantity")):
        errors.append(f"{prefix}_bad_quantity")
    if row.get("size") is not None and not isinstance(row.get("size"), str):
        errors.append(f"{prefix}_bad_size")
    for key in ("add", "remove"):
        if not isinstance(row.get(key), list) or not all(isinstance(x, str) for x in row.get(key, [])):
            errors.append(f"{prefix}_bad_{key}")
    if not isinstance(row.get("special_instructions"), str):
        errors.append(f"{prefix}_bad_special_instructions")
    return errors


def constraints_schema_errors(obj: Any, prefix: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(obj, dict):
        return [f"{prefix}_not_object"]
    if set(obj) != {"allergens", "dietary"}:
        errors.append(f"{prefix}_bad_keys")
    for key in ("allergens", "dietary"):
        if not isinstance(obj.get(key), list) or not all(isinstance(x, str) for x in obj.get(key, [])):
            errors.append(f"{prefix}_bad_{key}")
    return errors


def order_schema_errors(obj: Any, prefix: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(obj, dict):
        return [f"{prefix}_not_object"]
    if set(obj) != {"items", "constraints"}:
        errors.append(f"{prefix}_bad_keys")
    if not isinstance(obj.get("items"), list):
        errors.append(f"{prefix}_items_not_list")
    else:
        for idx, row in enumerate(obj["items"]):
            errors.extend(item_schema_errors(row, f"{prefix}_item_{idx}"))
    errors.extend(constraints_schema_errors(obj.get("constraints"), f"{prefix}_constraints"))
    return errors


def rewrite_schema_errors(obj: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required = {"status", "updated_order", "clarification_question", "reasons"}
    if set(obj) - required:
        errors.append("extra_top_level")
    if required - set(obj):
        errors.append("missing_top_level")
    if obj.get("status") not in STATUS_VALUES:
        errors.append("bad_status")
    errors.extend(order_schema_errors(obj.get("updated_order"), "updated_order"))
    if obj.get("clarification_question") is not None and not isinstance(obj.get("clarification_question"), str):
        errors.append("bad_clarification_question")
    if not isinstance(obj.get("reasons"), list) or not all(isinstance(x, str) for x in obj.get("reasons", [])):
        errors.append("bad_reasons")
    return errors


def line_item_schema_errors(row: Any, prefix: str) -> list[str]:
    if not isinstance(row, dict):
        return [f"{prefix}_not_object"]
    errors: list[str] = []
    if set(row) != {"line_id", "sku", "quantity", "size", "add", "remove", "special_instructions"}:
        errors.append(f"{prefix}_bad_keys")
    if not isinstance(row.get("line_id"), str) or not row.get("line_id"):
        errors.append(f"{prefix}_bad_line_id")
    errors.extend(item_schema_errors({key: value for key, value in row.items() if key != "line_id"}, prefix))
    return errors


def line_order_schema_errors(obj: Any, prefix: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(obj, dict):
        return [f"{prefix}_not_object"]
    if set(obj) != {"items", "constraints"}:
        errors.append(f"{prefix}_bad_keys")
    if not isinstance(obj.get("items"), list):
        errors.append(f"{prefix}_items_not_list")
    else:
        for idx, row in enumerate(obj["items"]):
            errors.extend(line_item_schema_errors(row, f"{prefix}_item_{idx}"))
        try:
            line_map(obj)
        except StateError as exc:
            errors.append(f"{prefix}_{exc}")
    errors.extend(constraints_schema_errors(obj.get("constraints"), f"{prefix}_constraints"))
    return errors


def rewrite_with_ids_schema_errors(obj: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required = {"status", "updated_order", "clarification_question", "reasons"}
    if set(obj) != required:
        errors.append("bad_top_level_keys")
    if obj.get("status") not in STATUS_VALUES:
        errors.append("bad_status")
    errors.extend(line_order_schema_errors(obj.get("updated_order"), "updated_order"))
    if obj.get("clarification_question") is not None and not isinstance(obj.get("clarification_question"), str):
        errors.append("bad_clarification_question")
    if not isinstance(obj.get("reasons"), list) or not all(isinstance(x, str) for x in obj.get("reasons", [])):
        errors.append("bad_reasons")
    return errors


def operation_schema_errors(op: Any, idx: int) -> list[str]:
    prefix = f"operation_{idx}"
    if not isinstance(op, dict):
        return [f"{prefix}_not_object"]
    errors: list[str] = []
    shapes = {
        "add_item": {"op", "item", "reason"},
        "remove_line": {"op", "line_id", "reason"},
        "update_line": {"op", "line_id", "changes", "reason"},
        "set_constraints": {"op", "constraints", "reason"},
    }
    kind = op.get("op")
    if kind not in shapes:
        errors.append(f"{prefix}_bad_op")
        return errors
    if set(op) != shapes[kind]:
        errors.append(f"{prefix}_bad_keys")
    if "line_id" in shapes[kind] and (not isinstance(op.get("line_id"), str) or not op.get("line_id")):
        errors.append(f"{prefix}_bad_line_id")
    if kind == "add_item":
        errors.extend(item_schema_errors(op.get("item"), f"{prefix}_item"))
    elif kind == "update_line":
        changes = op.get("changes")
        allowed = {"quantity", "size", "add", "remove", "special_instructions"}
        if not isinstance(changes, dict) or not changes:
            errors.append(f"{prefix}_bad_changes")
        else:
            if set(changes) - allowed:
                errors.append(f"{prefix}_changes_extra_keys")
            if "quantity" in changes and not valid_quantity(changes["quantity"]):
                errors.append(f"{prefix}_bad_quantity")
            if "size" in changes and changes["size"] is not None and not isinstance(changes["size"], str):
                errors.append(f"{prefix}_bad_size")
            for key in ("add", "remove"):
                if key in changes and (
                    not isinstance(changes[key], list) or not all(isinstance(x, str) for x in changes[key])
                ):
                    errors.append(f"{prefix}_bad_{key}")
            if "special_instructions" in changes and not isinstance(changes["special_instructions"], str):
                errors.append(f"{prefix}_bad_special_instructions")
    elif kind == "set_constraints":
        errors.extend(constraints_schema_errors(op.get("constraints"), f"{prefix}_constraints"))
    if not isinstance(op.get("reason"), str):
        errors.append(f"{prefix}_bad_reason")
    return errors


def patch_schema_errors(obj: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required = {"status", "base_version", "operations", "clarification_question", "reasons"}
    if set(obj) != required:
        errors.append("bad_top_level_keys")
    if obj.get("status") not in STATUS_VALUES:
        errors.append("bad_status")
    if type(obj.get("base_version")) is not int or obj.get("base_version", 0) < 1:
        errors.append("bad_base_version")
    if not isinstance(obj.get("operations"), list):
        errors.append("operations_not_list")
    else:
        for idx, op in enumerate(obj["operations"]):
            errors.extend(operation_schema_errors(op, idx))
    if obj.get("clarification_question") is not None and not isinstance(obj.get("clarification_question"), str):
        errors.append("bad_clarification_question")
    if not isinstance(obj.get("reasons"), list) or not all(isinstance(x, str) for x in obj.get("reasons", [])):
        errors.append("bad_reasons")
    return errors


def json_patch_schema_errors(obj: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required = {"status", "patch", "clarification_question", "reasons"}
    if set(obj) != required:
        errors.append("bad_top_level_keys")
    if obj.get("status") not in STATUS_VALUES:
        errors.append("bad_status")
    patch = obj.get("patch")
    if not isinstance(patch, list):
        errors.append("patch_not_list")
    else:
        for idx, operation in enumerate(patch):
            prefix = f"json_patch_{idx}"
            if not isinstance(operation, dict):
                errors.append(f"{prefix}_not_object")
                continue
            kind = operation.get("op")
            required_keys = {"op", "path"} if kind == "remove" else {"op", "path", "value"}
            if kind not in {"test", "add", "remove", "replace"}:
                errors.append(f"{prefix}_bad_op")
            if set(operation) != required_keys:
                errors.append(f"{prefix}_bad_keys")
            if not isinstance(operation.get("path"), str) or not operation.get("path", "").startswith("/"):
                errors.append(f"{prefix}_bad_path")
    if obj.get("clarification_question") is not None and not isinstance(obj.get("clarification_question"), str):
        errors.append("bad_clarification_question")
    if not isinstance(obj.get("reasons"), list) or not all(isinstance(x, str) for x in obj.get("reasons", [])):
        errors.append("bad_reasons")
    return errors


def _find_line(items: list[dict[str, Any]], line_id: str | None) -> dict[str, Any] | None:
    for row in items:
        if row.get("line_id") == line_id:
            return row
    return None


def _next_new_line_id(items: list[dict[str, Any]]) -> str:
    existing = {row.get("line_id") for row in items if isinstance(row, dict)}
    index = 1
    while f"N{index}" in existing:
        index += 1
    return f"N{index}"


def apply_operations(
    current_order: dict[str, Any],
    patch: dict[str, Any],
    expected_version: int = 1,
) -> tuple[dict[str, Any], bool, str | None]:
    original = copy.deepcopy(current_order)
    order = copy.deepcopy(current_order)
    order.setdefault("items", [])
    order.setdefault("constraints", {"allergens": [], "dietary": []})
    errors: list[str] = []

    try:
        line_map(order)
    except StateError as exc:
        return original, False, str(exc)
    if patch.get("base_version") != expected_version:
        return original, False, "stale_base_version"

    operations = patch.get("operations")
    if not isinstance(operations, list):
        return original, False, "operations_not_list"
    for idx, op in enumerate(operations):
        errors.extend(operation_schema_errors(op, idx))
    if errors:
        return original, False, ";".join(errors)

    touched: set[str] = set()
    for op in operations:
        kind = op["op"]
        touch = "/constraints" if kind == "set_constraints" else (
            "/new-line" if kind == "add_item" else f"/lines/{op['line_id']}"
        )
        if touch in touched and touch != "/new-line":
            errors.append(f"conflicting_write:{touch}")
            break
        touched.add(touch)

        if kind == "set_constraints":
            order["constraints"] = copy.deepcopy(op["constraints"])
            continue
        if kind == "add_item":
            new_item = copy.deepcopy(op["item"])
            new_item["line_id"] = _next_new_line_id(order["items"])
            order["items"].append(new_item)
            continue

        line = _find_line(order["items"], op["line_id"])
        if line is None:
            errors.append(f"{kind}_missing_line")
            break
        if kind == "remove_line":
            order["items"] = [row for row in order["items"] if row.get("line_id") != op["line_id"]]
        elif kind == "update_line":
            for key, value in op["changes"].items():
                line[key] = sorted(value) if key in {"add", "remove"} else value
    if errors:
        return original, False, ";".join(errors)
    return order, True, None


def _json_path_parts(path: str) -> list[str]:
    if not path.startswith("/"):
        raise StateError("json_patch_path_not_absolute")
    return [pointer_unescape(part) for part in path[1:].split("/")]


def _get_json_patch_value(state: dict[str, Any], parts: list[str]) -> Any:
    node: Any = state
    for part in parts:
        if not isinstance(node, dict) or part not in node:
            raise StateError("json_patch_path_missing")
        node = node[part]
    return node


def apply_json_patch(
    current_order: dict[str, Any],
    response: dict[str, Any],
    expected_version: int = 1,
) -> tuple[dict[str, Any], bool, str | None]:
    original = copy.deepcopy(current_order)
    try:
        state = order_to_state(current_order, expected_version)
    except StateError as exc:
        return original, False, str(exc)
    operations = response.get("patch")
    if not isinstance(operations, list) or not operations:
        return original, False, "missing_version_test"
    first = operations[0]
    if first != {"op": "test", "path": "/version", "value": expected_version}:
        return original, False, "missing_or_stale_version_test"

    written_paths: list[str] = []
    try:
        for operation in operations:
            kind = operation.get("op")
            path = operation.get("path")
            if not isinstance(path, str):
                raise StateError("json_patch_bad_path")
            parts = _json_path_parts(path)
            if kind == "test":
                if _get_json_patch_value(state, parts) != operation.get("value"):
                    raise StateError("json_patch_test_failed")
                continue
            if path == "/version" or not parts or parts[0] not in {"lines", "constraints"}:
                raise StateError("json_patch_forbidden_path")
            if any(
                path == previous
                or path.startswith(previous.rstrip("/") + "/")
                or previous.startswith(path.rstrip("/") + "/")
                for previous in written_paths
            ):
                raise StateError("json_patch_conflicting_write")
            written_paths.append(path)

            parent = state
            for part in parts[:-1]:
                if not isinstance(parent, dict) or part not in parent or not isinstance(parent[part], dict):
                    raise StateError("json_patch_parent_missing")
                parent = parent[part]
            key = parts[-1]
            if kind == "add":
                if key in parent:
                    raise StateError("json_patch_add_exists")
                parent[key] = copy.deepcopy(operation.get("value"))
            elif kind == "replace":
                if key not in parent:
                    raise StateError("json_patch_replace_missing")
                parent[key] = copy.deepcopy(operation.get("value"))
            elif kind == "remove":
                if key not in parent:
                    raise StateError("json_patch_remove_missing")
                del parent[key]
            else:
                raise StateError("json_patch_bad_op")
        applied = state_to_order(state)
        line_map(applied)
        if constraints_schema_errors(applied.get("constraints"), "constraints"):
            raise StateError("json_patch_bad_constraints")
        for idx, row in enumerate(applied["items"]):
            if line_item_schema_errors(row, f"line_{idx}"):
                raise StateError("json_patch_bad_line")
        return applied, True, None
    except StateError as exc:
        return original, False, str(exc)


DAIRY_ADDONS = {"cheese_sauce", "extra_cheese"}
MEAT_ADDONS = {"bacon", "extra_chicken"}


def line_conflicts_constraints(line: dict[str, Any], constraints: dict[str, Any]) -> bool:
    sku = line.get("sku")
    if sku not in MENU:
        return True
    allergens = set(constraints.get("allergens", []) if isinstance(constraints, dict) else [])
    dietary = set(constraints.get("dietary", []) if isinstance(constraints, dict) else [])
    add = set(line.get("add", []) if isinstance(line.get("add"), list) else [])
    remove = set(line.get("remove", []) if isinstance(line.get("remove"), list) else [])

    if "dairy" in allergens:
        dairy_default = (sku == "classic_burger" and "cheese" not in remove) or (
            sku == "margherita_pizza" and "mozzarella" not in remove
        ) or (sku == "chicken_wrap" and "yogurt_sauce" not in remove)
        if dairy_default or add & DAIRY_ADDONS:
            return True
    if "gluten" in allergens:
        gluten_safe_burger = sku == "classic_burger" and "bun" in remove and "gluten_free_bun" in add
        if "gluten" in MENU[sku]["allergens"] and not gluten_safe_burger:
            return True
    if "peanut" in allergens and "peanut" in MENU[sku]["allergens"]:
        return True
    if "soy" in allergens and "soy" in MENU[sku]["allergens"]:
        return True
    if "sesame" in allergens and sku == "vegan_bowl" and "sesame_dressing" not in remove:
        return True

    if "vegan" in dietary and (
        "vegan" not in MENU[sku]["tags"] or add & (DAIRY_ADDONS | MEAT_ADDONS | {"fried_egg"})
    ):
        return True
    return "vegetarian" in dietary and (
        sku in {"classic_burger", "chicken_wrap"} or bool(add & MEAT_ADDONS)
    )


def order_has_constraint_conflict(order: dict[str, Any] | None) -> bool:
    if not isinstance(order, dict) or not isinstance(order.get("constraints"), dict):
        return False
    for row in order.get("items", []) if isinstance(order.get("items"), list) else []:
        if isinstance(row, dict) and line_conflicts_constraints(row, order["constraints"]):
            return True
    return False


def protected_items_unchanged(case: dict[str, Any], applied_order: dict[str, Any] | None) -> bool:
    protected = set(case.get("unchanged_line_ids", []))
    if not protected:
        return True
    current = case.get("current_order", {})
    required = Counter(
        canonical_item(row)
        for row in current.get("items", [])
        if isinstance(row, dict) and row.get("line_id") in protected
    )
    return (item_counter(applied_order) & required) == required


def evaluate_text(text: str, case: dict[str, Any], mode: str) -> Evaluation:
    parsed, json_error = extract_json(text)
    if parsed is None:
        return Evaluation(
            json_valid=False,
            schema_valid=False,
            status_correct=False,
            order_exact=False,
            constraints_exact=False,
            state_preserved_when_blocked=False,
            semantic_ok=False,
            unsafe_state_change=False,
            unintended_drift=False,
            identity_error=False,
            identity_observable=mode != "rewrite",
            identity_fidelity=None if mode == "rewrite" else False,
            operation_executable=False,
            authorized_write_precision=None,
            authorized_write_recall=None,
            collateral_write_count=None,
            actual_state_diff=None,
            unexpected_state_diff=None,
            missing_expected_state_diff=None,
            error=json_error,
            parsed=None,
            applied_order=None,
        )

    schema_validators = {
        "rewrite": rewrite_schema_errors,
        "rewrite_with_ids": rewrite_with_ids_schema_errors,
        "line_patch": patch_schema_errors,
        "json_patch": json_patch_schema_errors,
    }
    if mode not in schema_validators:
        raise ValueError(f"unknown mode: {mode}")
    schema_error_list = schema_validators[mode](parsed)
    schema_valid = not schema_error_list
    operation_executable = True
    operation_error = None
    state_version = int(case.get("state_version", 1))
    if mode in {"rewrite", "rewrite_with_ids"}:
        applied_order = parsed.get("updated_order") if isinstance(parsed.get("updated_order"), dict) else None
    elif mode == "line_patch":
        if schema_valid:
            applied_order, operation_executable, operation_error = apply_operations(
                case["current_order"], parsed, state_version
            )
        else:
            applied_order, operation_executable, operation_error = (
                copy.deepcopy(case["current_order"]), False, "schema_invalid_no_execution"
            )
    else:
        if schema_valid:
            applied_order, operation_executable, operation_error = apply_json_patch(
                case["current_order"], parsed, state_version
            )
        else:
            applied_order, operation_executable, operation_error = (
                copy.deepcopy(case["current_order"]), False, "schema_invalid_no_execution"
            )

    status_correct = parsed.get("status") == case.get("expected_status")
    constraints_exact = constraints_tuple(applied_order) == constraints_tuple(case["expected_order"])
    identity_observable = mode != "rewrite"
    actual_diff: list[dict[str, Any]] | None = None
    unexpected_diff: list[dict[str, Any]] | None = None
    missing_diff: list[dict[str, Any]] | None = None
    authorized_precision: float | None = None
    authorized_recall: float | None = None
    collateral_write_count: int | None = None
    identity_fidelity: bool | None = None

    if identity_observable:
        order_exact = identity_orders_equal(applied_order, case["expected_order"])
        try:
            expected_diff = case.get("expected_writes") or state_diff(case["current_order"], case["expected_order"])
            actual_diff = state_diff(case["current_order"], applied_order or {})
            diff_score = score_diff(expected_diff, actual_diff)
            authorized_precision = diff_score.precision
            authorized_recall = diff_score.recall
            unexpected_diff = diff_score.unexpected
            missing_diff = diff_score.missing
            collateral_write_count = len(unexpected_diff)
            protected_ok = not any(
                diff_touches_path(actual_diff, path) for path in protected_paths_for_case(case)
            )
            identity_error = any(
                str(entry.get("path", "")).startswith("/lines/")
                and any(
                    str(entry.get("path")) == path or str(entry.get("path", "")).startswith(path + "/")
                    for path in protected_paths_for_case(case)
                    if path.startswith("/lines/")
                )
                for entry in unexpected_diff
            )
            identity_fidelity = not identity_error
        except StateError as exc:
            operation_executable = False
            operation_error = ";".join(filter(None, [operation_error, str(exc)]))
            protected_ok = False
            identity_error = True
            identity_fidelity = False
        state_preserved = order_exact if case.get("expected_status") != "accepted" else False
    else:
        expected_order = strip_line_ids(case["expected_order"])
        order_exact = item_counter(applied_order) == item_counter(expected_order)
        state_preserved = orders_equal(applied_order, expected_order) if case.get("expected_status") != "accepted" else False
        protected_ok = protected_items_unchanged(case, applied_order)
        identity_error = False

    unintended_drift = not protected_ok

    semantic_ok = (
        schema_valid
        and operation_executable
        and status_correct
        and order_exact
        and constraints_exact
    )
    if identity_observable:
        semantic_ok = semantic_ok and authorized_precision == 1.0 and authorized_recall == 1.0
    if case.get("expected_status") != "accepted":
        semantic_ok = semantic_ok and state_preserved

    unsafe_state_change = False
    if case.get("expected_status") != "accepted":
        if identity_observable:
            unsafe_state_change = parsed.get("status") == "accepted" or bool(unexpected_diff)
        else:
            unsafe_state_change = parsed.get("status") == "accepted" or not orders_equal(
                applied_order, strip_line_ids(case["expected_order"])
            )
    if parsed.get("status") == "accepted" and order_has_constraint_conflict(applied_order):
        unsafe_state_change = True

    errors = [*schema_error_list]
    if operation_error:
        errors.append(operation_error)
    return Evaluation(
        json_valid=True,
        schema_valid=schema_valid,
        status_correct=status_correct,
        order_exact=order_exact,
        constraints_exact=constraints_exact,
        state_preserved_when_blocked=state_preserved,
        semantic_ok=semantic_ok,
        unsafe_state_change=unsafe_state_change,
        unintended_drift=unintended_drift,
        identity_error=identity_error,
        identity_observable=identity_observable,
        identity_fidelity=identity_fidelity,
        operation_executable=operation_executable,
        authorized_write_precision=authorized_precision,
        authorized_write_recall=authorized_recall,
        collateral_write_count=collateral_write_count,
        actual_state_diff=actual_diff,
        unexpected_state_diff=unexpected_diff,
        missing_expected_state_diff=missing_diff,
        error=";".join(errors) if errors else None,
        parsed=parsed,
        applied_order=applied_order,
    )
