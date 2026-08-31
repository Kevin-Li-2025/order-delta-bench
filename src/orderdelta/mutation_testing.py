from __future__ import annotations

import argparse
import copy
import json
from collections import Counter
from pathlib import Path
from typing import Any

from .evaluate import evaluate_text
from .oracles import equivalent_response, expected_writes, oracle_response
from .state import identity_orders_equal

MODES = ("rewrite", "rewrite_with_ids", "line_patch", "json_patch")


def _json(response: dict[str, Any]) -> str:
    return json.dumps(response, sort_keys=True)


def _different_quantity(value: Any) -> int:
    return 2 if value != 2 else 3


def invalid_mutations(case: dict[str, Any], mode: str) -> list[tuple[str, dict[str, Any]]]:
    gold = oracle_response(case, mode)
    mutations: list[tuple[str, dict[str, Any]]] = []

    wrong_status = copy.deepcopy(gold)
    wrong_status["status"] = "accepted" if case["expected_status"] != "accepted" else "needs_clarification"
    mutations.append(("wrong_status", wrong_status))

    no_op = copy.deepcopy(gold)
    if mode in {"rewrite", "rewrite_with_ids"}:
        no_op["updated_order"] = copy.deepcopy(case["current_order"])
        if mode == "rewrite":
            for row in no_op["updated_order"]["items"]:
                row.pop("line_id", None)
    elif mode == "line_patch":
        no_op["operations"] = []
    else:
        no_op["patch"] = no_op["patch"][:1]
    if expected_writes(case):
        mutations.append(("missing_expected_write", no_op))

    if mode == "rewrite":
        constraint = copy.deepcopy(gold)
        constraint["updated_order"]["constraints"]["allergens"].append("mutation_only")
        mutations.append(("constraint_only_write", constraint))
        return mutations

    protected_ids = list(case.get("unchanged_line_ids", []))
    if mode == "rewrite_with_ids":
        constraint = copy.deepcopy(gold)
        constraint["updated_order"]["constraints"]["allergens"].append("mutation_only")
        mutations.append(("constraint_only_write", constraint))

        if protected_ids:
            protected = copy.deepcopy(gold)
            for row in protected["updated_order"]["items"]:
                if row.get("line_id") == protected_ids[0]:
                    row["quantity"] = _different_quantity(row.get("quantity"))
                    mutations.append(("protected_object_write", protected))
                    break
        if len(gold["updated_order"]["items"]) >= 2:
            swapped = copy.deepcopy(gold)
            first, second = swapped["updated_order"]["items"][:2]
            first["line_id"], second["line_id"] = second["line_id"], first["line_id"]
            if not identity_orders_equal(swapped["updated_order"], gold["updated_order"]):
                mutations.append(("swap_line_identities", swapped))
        if gold["updated_order"]["items"]:
            duplicate = copy.deepcopy(gold)
            duplicate["updated_order"]["items"].append(copy.deepcopy(duplicate["updated_order"]["items"][0]))
            mutations.append(("duplicate_line_identity", duplicate))
        return mutations

    if mode == "line_patch":
        stale = copy.deepcopy(gold)
        stale["base_version"] += 1
        mutations.append(("stale_version", stale))

        if protected_ids:
            protected = copy.deepcopy(gold)
            protected["operations"].append({
                "op": "update_line",
                "line_id": protected_ids[0],
                "changes": {"quantity": 20},
                "reason": "mutation",
            })
            mutations.append(("protected_object_write", protected))

        existing_ids = [row["line_id"] for row in case["current_order"]["items"]]
        if existing_ids:
            conflict = copy.deepcopy(gold)
            conflict["operations"] = [
                {"op": "remove_line", "line_id": existing_ids[0], "reason": "mutation"},
                {
                    "op": "update_line",
                    "line_id": existing_ids[0],
                    "changes": {"quantity": 2},
                    "reason": "mutation",
                },
            ]
            mutations.append(("remove_then_update", conflict))
        return mutations

    stale = copy.deepcopy(gold)
    stale["patch"][0]["value"] += 1
    mutations.append(("stale_version", stale))
    if protected_ids:
        line = next(row for row in case["current_order"]["items"] if row["line_id"] == protected_ids[0])
        protected = copy.deepcopy(gold)
        protected["patch"].append({
            "op": "replace",
            "path": f"/lines/{protected_ids[0]}/quantity",
            "value": _different_quantity(line["quantity"]),
        })
        mutations.append(("protected_object_write", protected))
    existing_ids = [row["line_id"] for row in case["current_order"]["items"]]
    if existing_ids:
        conflict = copy.deepcopy(gold)
        path = f"/lines/{existing_ids[0]}/quantity"
        conflict["patch"].extend([
            {"op": "replace", "path": path, "value": 2},
            {"op": "replace", "path": path, "value": 3},
        ])
        mutations.append(("conflicting_json_writes", conflict))
    return mutations


def audit_cases(cases: list[dict[str, Any]]) -> dict[str, Any]:
    survivors: list[dict[str, str]] = []
    false_rejections: list[dict[str, str]] = []
    gold_failures: list[dict[str, str]] = []
    operator_totals: Counter[str] = Counter()
    operator_kills: Counter[str] = Counter()

    for case in cases:
        for mode in MODES:
            gold = evaluate_text(_json(oracle_response(case, mode)), case, mode)
            if not gold.semantic_ok:
                gold_failures.append({"case_id": case["id"], "mode": mode, "error": gold.error or "semantic"})
                continue
            equivalent = evaluate_text(_json(equivalent_response(case, mode)), case, mode)
            if not equivalent.semantic_ok:
                false_rejections.append({"case_id": case["id"], "mode": mode, "error": equivalent.error or "semantic"})
            for operator, response in invalid_mutations(case, mode):
                operator_totals[operator] += 1
                evaluation = evaluate_text(_json(response), case, mode)
                if evaluation.semantic_ok:
                    survivors.append({"case_id": case["id"], "mode": mode, "operator": operator})
                else:
                    operator_kills[operator] += 1

    total = sum(operator_totals.values())
    killed = sum(operator_kills.values())
    alternatives = len(cases) * len(MODES)
    return {
        "cases": len(cases),
        "modes": list(MODES),
        "gold_outputs": alternatives,
        "gold_failures": gold_failures,
        "invalid_mutations": total,
        "killed_mutations": killed,
        "kill_rate": killed / total if total else 1.0,
        "survivors": survivors,
        "equivalent_alternatives": alternatives,
        "false_rejections": false_rejections,
        "false_rejection_rate": len(false_rejections) / alternatives if alternatives else 0.0,
        "by_operator": {
            operator: {
                "total": operator_totals[operator],
                "killed": operator_kills[operator],
                "kill_rate": operator_kills[operator] / operator_totals[operator],
            }
            for operator in sorted(operator_totals)
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    cases = [json.loads(line) for line in args.dataset.read_text(encoding="utf-8").splitlines() if line.strip()]
    report = audit_cases(cases)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"killed {report['killed_mutations']}/{report['invalid_mutations']} invalid mutations; "
        f"false rejections {len(report['false_rejections'])}/{report['equivalent_alternatives']}"
    )
    if report["gold_failures"] or report["survivors"] or report["false_rejection_rate"] >= 0.005:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
