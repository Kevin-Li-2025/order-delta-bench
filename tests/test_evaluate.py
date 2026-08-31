from __future__ import annotations

import copy
import json
import unittest

from src.orderdelta.evaluate import (
    evaluate_text,
    item_schema_errors,
    operation_schema_errors,
)
from src.orderdelta.generate_dataset import build_cases


class QuantityContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.case = build_cases(1)[0]

    def test_item_quantity_accepts_public_bounds(self) -> None:
        item = copy.deepcopy(self.case["expected_order"]["items"][0])
        item.pop("line_id")

        for quantity in (1, 20):
            with self.subTest(quantity=quantity):
                item["quantity"] = quantity
                self.assertNotIn("item_bad_quantity", item_schema_errors(item, "item"))

    def test_item_quantity_rejects_bool_and_out_of_range_values(self) -> None:
        item = copy.deepcopy(self.case["expected_order"]["items"][0])
        item.pop("line_id")

        for quantity in (True, False, 0, 21, 1.5, "2"):
            with self.subTest(quantity=quantity):
                item["quantity"] = quantity
                self.assertIn("item_bad_quantity", item_schema_errors(item, "item"))

    def test_patch_quantity_uses_the_same_bounds(self) -> None:
        operation = {
            "op": "update_line",
            "line_id": "L1",
            "changes": {"quantity": 21},
            "reason": "invalid upper bound",
        }

        self.assertIn(
            "operation_0_bad_quantity",
            operation_schema_errors(operation, 0),
        )

    def test_rewrite_over_public_max_is_not_schema_valid(self) -> None:
        updated_order = copy.deepcopy(self.case["expected_order"])
        for row in updated_order["items"]:
            row.pop("line_id", None)
        updated_order["items"][-1]["quantity"] = 21
        response = {
            "status": "accepted",
            "updated_order": updated_order,
            "clarification_question": None,
            "reasons": [],
        }

        evaluation = evaluate_text(json.dumps(response), self.case, "rewrite")

        self.assertFalse(evaluation.schema_valid)
        self.assertFalse(evaluation.semantic_ok)
        self.assertIn("updated_order_item_1_bad_quantity", evaluation.error or "")


if __name__ == "__main__":
    unittest.main()
