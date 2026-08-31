from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.orderdelta.run_nebius import counterbalanced_tasks, load_seen
from src.orderdelta.snapshot_nebius_models import sanitized_snapshot


class ReplicateProtocolTests(unittest.TestCase):
    def test_counterbalancing_keeps_replicates_distinct_and_complete(self) -> None:
        rows = [{"id": "case-1", "category": "test"}]
        modes = ["rewrite_with_ids", "line_patch", "json_patch"]

        tasks = counterbalanced_tasks(
            ["model-1"], modes, rows, seen=set(), seed=7, replicates=3
        )

        keys = {(model, mode, row["id"], replicate) for model, mode, row, _, replicate in tasks}
        self.assertEqual(len(keys), 9)
        for replicate in range(3):
            self.assertEqual(
                {mode for model, mode, _, observed in keys if model == "model-1" and observed == replicate},
                set(modes),
            )

    def test_resume_key_and_experiment_id_fail_closed(self) -> None:
        record = {
            "model": "model-1",
            "mode": "line_patch",
            "case": {"id": "case-1"},
            "protocol": {"experiment_id": "exp-a", "replicate_index": 2},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.jsonl"
            path.write_text(json.dumps(record) + "\n", encoding="utf-8")
            self.assertEqual(load_seen(path, "exp-a"), {("model-1", "line_patch", "case-1", 2)})
            with self.assertRaises(ValueError):
                load_seen(path, "exp-b")


class ModelCatalogTests(unittest.TestCase):
    def test_snapshot_requires_structured_outputs_and_drops_unknown_fields(self) -> None:
        catalog = [
            {
                "id": "model-1",
                "pricing": {"prompt": "0.1", "completion": "0.2"},
                "supported_features": ["structured_outputs"],
                "credential_like_field": "must-not-be-copied",
            }
        ]

        snapshot = sanitized_snapshot(catalog, ["model-1"], "https://example.test/v1/")

        self.assertEqual(snapshot["selection_gate"], "advertises_structured_outputs")
        self.assertNotIn("credential_like_field", snapshot["models"][0])
        with self.assertRaises(ValueError):
            sanitized_snapshot(
                [{"id": "model-2", "supported_features": ["tools"]}],
                ["model-2"],
                "https://example.test/v1/",
            )


if __name__ == "__main__":
    unittest.main()
