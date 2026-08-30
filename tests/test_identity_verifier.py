from __future__ import annotations

import json
import unittest

from jsonschema import Draft202012Validator

from src.orderdelta.contracts import RESPONSE_FORMATS
from src.orderdelta.evaluate import evaluate_text
from src.orderdelta.generate_dataset import build_cases
from src.orderdelta.mutation_testing import audit_cases
from src.orderdelta.oracles import oracle_response
from src.orderdelta.prompts import build_user_prompt


def _item(line_id: str, quantity: int) -> dict:
    return {
        "line_id": line_id,
        "sku": "cola",
        "quantity": quantity,
        "size": "regular",
        "add": [],
        "remove": [],
        "special_instructions": "",
    }


class IdentityVerifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.case = {
            "id": "identity_collision_000",
            "category": "identity_collision",
            "utterance": "Make L1 two.",
            "current_order": {
                "items": [_item("L1", 1), _item("L2", 1)],
                "constraints": {"allergens": [], "dietary": []},
            },
            "expected_order": {
                "items": [_item("L1", 2), _item("L2", 1)],
                "constraints": {"allergens": [], "dietary": []},
            },
            "expected_status": "accepted",
            "expected_reasons": [],
            "target_line_ids": ["L1"],
            "unchanged_line_ids": ["L2"],
            "state_version": 1,
        }

    def test_identity_aware_rewrite_kills_value_equivalent_wrong_object(self) -> None:
        wrong = oracle_response(self.case, "rewrite_with_ids")
        wrong["updated_order"]["items"] = [_item("L1", 1), _item("L2", 2)]

        evaluation = evaluate_text(json.dumps(wrong), self.case, "rewrite_with_ids")

        self.assertFalse(evaluation.semantic_ok)
        self.assertTrue(evaluation.identity_error)
        self.assertEqual(evaluation.authorized_write_precision, 0.0)
        self.assertEqual(evaluation.authorized_write_recall, 0.0)

    def test_legacy_rewrite_marks_identity_unobservable(self) -> None:
        wrong = oracle_response(self.case, "rewrite")
        wrong["updated_order"]["items"] = [
            {key: value for key, value in _item("L1", 1).items() if key != "line_id"},
            {key: value for key, value in _item("L2", 2).items() if key != "line_id"},
        ]

        evaluation = evaluate_text(json.dumps(wrong), self.case, "rewrite")

        self.assertTrue(evaluation.semantic_ok)
        self.assertFalse(evaluation.identity_observable)
        self.assertIsNone(evaluation.identity_fidelity)

    def test_custom_patch_rolls_back_all_writes_after_failure(self) -> None:
        response = oracle_response(self.case, "line_patch")
        response["operations"].append({
            "op": "update_line",
            "line_id": "MISSING",
            "changes": {"quantity": 3},
            "reason": "invalid second write",
        })

        evaluation = evaluate_text(json.dumps(response), self.case, "line_patch")

        self.assertFalse(evaluation.operation_executable)
        self.assertEqual(evaluation.applied_order, self.case["current_order"])
        self.assertEqual(evaluation.actual_state_diff, [])

    def test_json_patch_stale_version_rolls_back(self) -> None:
        response = oracle_response(self.case, "json_patch")
        response["patch"][0]["value"] = 2

        evaluation = evaluate_text(json.dumps(response), self.case, "json_patch")

        self.assertFalse(evaluation.operation_executable)
        self.assertEqual(evaluation.applied_order, self.case["current_order"])

    def test_schema_invalid_patch_is_never_executed(self) -> None:
        response = oracle_response(self.case, "line_patch")
        response["unexpected"] = "must fail closed"

        evaluation = evaluate_text(json.dumps(response), self.case, "line_patch")

        self.assertFalse(evaluation.schema_valid)
        self.assertFalse(evaluation.operation_executable)
        self.assertEqual(evaluation.applied_order, self.case["current_order"])
        self.assertIn("schema_invalid_no_execution", evaluation.error or "")


class ControlledInterfaceTests(unittest.TestCase):
    def test_gold_outputs_conform_to_published_json_schemas(self) -> None:
        for case in build_cases(1):
            for mode, response_format in RESPONSE_FORMATS.items():
                schema = response_format["json_schema"]["schema"]
                Draft202012Validator.check_schema(schema)
                Draft202012Validator(schema).validate(oracle_response(case, mode))

    def test_identity_bearing_modes_receive_the_same_state_information(self) -> None:
        case = build_cases(1)[0]
        states = [json.loads(build_user_prompt(case, mode))["current_state"] for mode in (
            "rewrite_with_ids",
            "line_patch",
            "json_patch",
        )]
        self.assertEqual(states[0], states[1])
        self.assertEqual(states[1], states[2])

    def test_dataset_carries_cluster_and_authorization_metadata(self) -> None:
        case = build_cases(1)[0]
        self.assertEqual(case["state_version"], 1)
        self.assertIn("semantic_program_id", case)
        self.assertIn("template_family_id", case)
        self.assertTrue(case["expected_writes"])
        self.assertIn("/constraints", case["protected_paths"])

    def test_full_mutation_audit_has_no_survivors_or_false_rejections(self) -> None:
        report = audit_cases(build_cases(1))
        self.assertEqual(report["gold_failures"], [])
        self.assertEqual(report["survivors"], [])
        self.assertEqual(report["false_rejections"], [])
        self.assertGreater(report["invalid_mutations"], 200)


if __name__ == "__main__":
    unittest.main()
