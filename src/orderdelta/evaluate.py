from __future__ import annotations

import copy
import json
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

from src.orderbench.contracts import MENU

from .contracts import STATUS_VALUES

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
    operation_executable: bool
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
            "operation_executable": self.operation_executable,
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


def operation_schema_errors(op: Any, idx: int) -> list[str]:
    prefix = f"operation_{idx}"
    errors: list[str] = []
    if not isinstance(op, dict):
        return [f"{prefix}_not_object"]
    required = {
        "op",
        "line_id",
        "item",
        "quantity",
        "size",
        "add",
        "remove",
        "remove_add",
        "remove_remove",
        "constraints",
        "reason",
    }
    if set(op) - required:
        errors.append(f"{prefix}_extra_keys")
    if required - set(op):
        errors.append(f"{prefix}_missing_keys")
    if op.get("op") not in {"add_item", "remove_line", "update_line", "set_constraints", "noop"}:
        errors.append(f"{prefix}_bad_op")
    if op.get("line_id") is not None and not isinstance(op.get("line_id"), str):
        errors.append(f"{prefix}_bad_line_id")
    if op.get("item") is not None:
        errors.extend(item_schema_errors(op.get("item"), f"{prefix}_item"))
    if op.get("quantity") is not None and not valid_quantity(op.get("quantity")):
        errors.append(f"{prefix}_bad_quantity")
    if op.get("size") is not None and not isinstance(op.get("size"), str):
        errors.append(f"{prefix}_bad_size")
    for key in ("add", "remove", "remove_add", "remove_remove"):
        if not isinstance(op.get(key), list) or not all(isinstance(x, str) for x in op.get(key, [])):
            errors.append(f"{prefix}_bad_{key}")
    if op.get("constraints") is not None:
        errors.extend(constraints_schema_errors(op.get("constraints"), f"{prefix}_constraints"))
    if not isinstance(op.get("reason"), str):
        errors.append(f"{prefix}_bad_reason")
    return errors


def patch_schema_errors(obj: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required = {"status", "operations", "clarification_question", "reasons"}
    if set(obj) - required:
        errors.append("extra_top_level")
    if required - set(obj):
        errors.append("missing_top_level")
    if obj.get("status") not in STATUS_VALUES:
        errors.append("bad_status")
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


def _find_line(items: list[dict[str, Any]], line_id: str | None) -> dict[str, Any] | None:
    for row in items:
        if row.get("line_id") == line_id:
            return row
    return None


def apply_operations(current_order: dict[str, Any], patch: dict[str, Any]) -> tuple[dict[str, Any], bool, str | None]:
    order = copy.deepcopy(current_order)
    order.setdefault("items", [])
    order.setdefault("constraints", {"allergens": [], "dietary": []})
    executable = True
    errors: list[str] = []
    next_new = 1

    for op in patch.get("operations", []) if isinstance(patch.get("operations"), list) else []:
        if not isinstance(op, dict):
            executable = False
            errors.append("bad_operation")
            continue
        kind = op.get("op")
        if kind == "noop":
            continue
        if kind == "set_constraints":
            if isinstance(op.get("constraints"), dict):
                order["constraints"] = copy.deepcopy(op["constraints"])
            else:
                executable = False
                errors.append("set_constraints_missing_constraints")
            continue
        if kind == "add_item":
            if isinstance(op.get("item"), dict):
                new_item = copy.deepcopy(op["item"])
                new_item["line_id"] = op.get("line_id") if isinstance(op.get("line_id"), str) else f"NEW{next_new}"
                next_new += 1
                order["items"].append(new_item)
            else:
                executable = False
                errors.append("add_item_missing_item")
            continue

        line = _find_line(order["items"], op.get("line_id"))
        if line is None:
            executable = False
            errors.append(f"{kind}_missing_line")
            continue
        if kind == "remove_line":
            order["items"] = [row for row in order["items"] if row.get("line_id") != op.get("line_id")]
        elif kind == "update_line":
            if op.get("quantity") is not None:
                line["quantity"] = op["quantity"]
            if op.get("size") is not None:
                line["size"] = op["size"]
            for key in ("add", "remove"):
                values = set(line.get(key, []))
                values.update(op.get(key, []) if isinstance(op.get(key), list) else [])
                line[key] = sorted(values)
            if isinstance(op.get("remove_add"), list):
                line["add"] = sorted(set(line.get("add", [])) - set(op["remove_add"]))
            if isinstance(op.get("remove_remove"), list):
                line["remove"] = sorted(set(line.get("remove", [])) - set(op["remove_remove"]))
        else:
            executable = False
            errors.append(f"unknown_op:{kind}")
    return order, executable, ";".join(errors) if errors else None


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

    if "vegan" in dietary:
        if "vegan" not in MENU[sku]["tags"] or add & (DAIRY_ADDONS | MEAT_ADDONS | {"fried_egg"}):
            return True
    if "vegetarian" in dietary:
        if sku in {"classic_burger", "chicken_wrap"} or add & MEAT_ADDONS:
            return True
    return False


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
            operation_executable=False,
            error=json_error,
            parsed=None,
            applied_order=None,
        )

    schema_error_list = rewrite_schema_errors(parsed) if mode == "rewrite" else patch_schema_errors(parsed)
    schema_valid = not schema_error_list
    operation_executable = True
    operation_error = None
    if mode == "rewrite":
        applied_order = parsed.get("updated_order") if isinstance(parsed.get("updated_order"), dict) else None
    else:
        applied_line_order, operation_executable, operation_error = apply_operations(case["current_order"], parsed)
        applied_order = strip_line_ids(applied_line_order)

    current_order = strip_line_ids(case["current_order"])
    expected_order = strip_line_ids(case["expected_order"])
    status_correct = parsed.get("status") == case.get("expected_status")
    order_exact = item_counter(applied_order) == item_counter(expected_order)
    constraints_exact = constraints_tuple(applied_order) == constraints_tuple(expected_order)
    state_preserved = orders_equal(applied_order, current_order)
    if case.get("expected_status") != "accepted":
        state_preserved = item_counter(applied_order) == item_counter(current_order)

    protected_ok = protected_items_unchanged(case, applied_order)
    unintended_drift = not protected_ok
    identity_error = bool(case.get("target_line_ids")) and not status_correct is False and not protected_ok

    semantic_ok = (
        schema_valid
        and operation_executable
        and status_correct
        and order_exact
        and constraints_exact
    )
    if case.get("expected_status") != "accepted":
        semantic_ok = semantic_ok and state_preserved

    unsafe_state_change = False
    if case.get("expected_status") != "accepted":
        unsafe_state_change = parsed.get("status") == "accepted" or item_counter(applied_order) != item_counter(current_order)
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
        operation_executable=operation_executable,
        error=";".join(errors) if errors else None,
        parsed=parsed,
        applied_order=applied_order,
    )
