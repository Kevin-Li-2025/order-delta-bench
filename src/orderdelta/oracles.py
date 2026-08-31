from __future__ import annotations

import copy
from typing import Any

from .evaluate import strip_line_ids
from .state import state_diff


def expected_writes(case: dict[str, Any]) -> list[dict[str, Any]]:
    writes = case.get("expected_writes")
    if isinstance(writes, list):
        return copy.deepcopy(writes)
    return state_diff(case["current_order"], case["expected_order"])


def _base_response(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": case["expected_status"],
        "clarification_question": None,
        "reasons": copy.deepcopy(case.get("expected_reasons", [])),
    }


def _line_patch_operations(case: dict[str, Any]) -> list[dict[str, Any]]:
    operations: list[dict[str, Any]] = []
    changes_by_line: dict[str, dict[str, Any]] = {}
    for write in expected_writes(case):
        path = str(write["path"])
        parts = path.strip("/").split("/")
        if parts[0] == "constraints":
            continue
        line_id = parts[1]
        if write["op"] == "remove":
            operations.append({"op": "remove_line", "line_id": line_id, "reason": "oracle remove"})
        elif write["op"] == "add":
            operations.append({"op": "add_item", "item": copy.deepcopy(write["after"]), "reason": "oracle add"})
        else:
            changes_by_line.setdefault(line_id, {})[parts[2]] = copy.deepcopy(write["after"])
    for line_id in sorted(changes_by_line):
        operations.append({
            "op": "update_line",
            "line_id": line_id,
            "changes": changes_by_line[line_id],
            "reason": "oracle update",
        })
    if any(str(write["path"]).startswith("/constraints/") for write in expected_writes(case)):
        operations.append({
            "op": "set_constraints",
            "constraints": copy.deepcopy(case["expected_order"]["constraints"]),
            "reason": "oracle constraint update",
        })
    return operations


def oracle_response(case: dict[str, Any], mode: str) -> dict[str, Any]:
    response = _base_response(case)
    if mode == "rewrite":
        response["updated_order"] = strip_line_ids(case["expected_order"])
    elif mode == "rewrite_with_ids":
        response["updated_order"] = copy.deepcopy(case["expected_order"])
    elif mode == "line_patch":
        response["base_version"] = int(case.get("state_version", 1))
        response["operations"] = _line_patch_operations(case)
    elif mode == "json_patch":
        patch = [{"op": "test", "path": "/version", "value": int(case.get("state_version", 1))}]
        for write in expected_writes(case):
            operation = {"op": write["op"], "path": write["path"]}
            if write["op"] != "remove":
                operation["value"] = copy.deepcopy(write["after"])
            patch.append(operation)
        response["patch"] = patch
    else:
        raise ValueError(f"unknown mode: {mode}")
    return response


def equivalent_response(case: dict[str, Any], mode: str) -> dict[str, Any]:
    response = oracle_response(case, mode)
    if mode in {"rewrite", "rewrite_with_ids"}:
        response["updated_order"]["items"] = list(reversed(response["updated_order"]["items"]))
    elif mode == "line_patch":
        response["operations"] = list(reversed(response["operations"]))
    elif mode == "json_patch":
        response["patch"] = response["patch"][:1] + list(reversed(response["patch"][1:]))
    return response
