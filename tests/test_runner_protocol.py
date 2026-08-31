from __future__ import annotations

import json
import gzip
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.orderdelta.analyze import (
    _benjamini_hochberg,
    _cluster_sign_flip_p,
    read_jsonl,
    reliability_tables,
)
from src.orderdelta.evaluate import evaluate_text
from src.orderdelta.oracles import oracle_response
from src.orderdelta.run_nebius import (
    PROTOCOL_SOURCE_PATHS,
    counterbalanced_tasks,
    load_seen,
    source_manifest,
)
from src.orderdelta.snapshot_nebius_models import sanitized_snapshot
from src.orderdelta_tools.audit_provider_run import audit_runs, content_sha256, file_sha256
from src.orderdelta_tools.replay_provider_evaluations import replay_evaluations


class ReplicateProtocolTests(unittest.TestCase):
    def test_protocol_source_manifest_covers_transitive_runtime_inputs(self) -> None:
        self.assertIn("orderbench/contracts.py", PROTOCOL_SOURCE_PATHS)
        self.assertIn("orderdelta/evaluate.py", PROTOCOL_SOURCE_PATHS)
        self.assertNotIn("orderdelta/analyze.py", PROTOCOL_SOURCE_PATHS)
        self.assertEqual(set(source_manifest()), set(PROTOCOL_SOURCE_PATHS))

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


class ProviderAuditTests(unittest.TestCase):
    def test_audit_requires_every_model_mode_case_replicate_key(self) -> None:
        modes = ["rewrite_with_ids", "line_patch", "json_patch"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = root / "dataset.jsonl"
            catalog = root / "catalog.json"
            raw = root / "raw.jsonl"
            dataset.write_text(json.dumps({"id": "case-1"}) + "\n", encoding="utf-8")
            catalog.write_text(
                json.dumps({
                    "models": [{
                        "id": "model-1",
                        "pricing": {"prompt": "0.000001", "completion": "0.000002"},
                    }]
                }) + "\n",
                encoding="utf-8",
            )
            rows = []
            for replicate in range(2):
                for mode in modes:
                    rows.append({
                        "model": "model-1",
                        "mode": mode,
                        "case": {"id": "case-1"},
                        "protocol": {
                            "experiment_id": "exp-a",
                            "replicate_index": replicate,
                            "dataset_sha256": file_sha256(dataset),
                            "model_catalog_sha256": file_sha256(catalog),
                            "source_sha256": "source-digest",
                            "generation_config": {"temperature": 0, "max_tokens": 10},
                        },
                        "result": {
                            "ok": True,
                            "finish_reason": "stop",
                            "provider_model": "model-1-build-a",
                            "provider_request_id": f"request-{replicate}-{mode}",
                            "model_fingerprint": "fp-a",
                            "retry_attempt": 0,
                            "schema_enforcement_mode": "strict_json_schema",
                            "submission_timestamp": "2026-08-31T00:00:00+00:00",
                            "response_timestamp": "2026-08-31T00:00:01+00:00",
                            "latency_s": 1.0,
                            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                        },
                    })
            raw.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

            report = audit_runs([raw], dataset, catalog, "exp-a", 2, modes)

            self.assertTrue(report["structurally_complete"])
            self.assertEqual(report["observed_unique_calls"], 6)
            self.assertAlmostEqual(report["estimated_usd"], 0.00012)
            self.assertEqual(report["model_fingerprints"], {"model-1|fp-a": 6})
            self.assertEqual(report["retry_attempts"], {"0": 6})
            self.assertEqual(report["provider_request_ids"], 6)
            self.assertEqual(report["duplicate_provider_request_ids"], 0)
            self.assertEqual(report["per_model"]["model-1"]["mean_latency_s"], 1.0)

            compressed = root / "raw.jsonl.gz"
            with gzip.open(compressed, "wt", encoding="utf-8") as stream:
                stream.write(raw.read_text(encoding="utf-8"))
            compressed_report = audit_runs([compressed], dataset, catalog, "exp-a", 2, modes)
            self.assertTrue(compressed_report["structurally_complete"])
            self.assertEqual(content_sha256(compressed), file_sha256(raw))

    def test_evaluation_replay_detects_tampering(self) -> None:
        case = json.loads(
            Path("data/orderdelta_v3_identity_controlled.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()[0]
        )
        content = json.dumps(oracle_response(case, "line_patch"))
        evaluation = evaluate_text(content, case, "line_patch").to_dict()
        row = {
            "model": "model-1",
            "mode": "line_patch",
            "case": case,
            "protocol": {"replicate_index": 0},
            "result": {"content": content},
            "evaluation": evaluation,
        }
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory) / "raw.jsonl"
            raw.write_text(json.dumps(row) + "\n", encoding="utf-8")
            self.assertTrue(replay_evaluations([raw])["replay_consistent"])
            row["evaluation"]["semantic_ok"] = not row["evaluation"]["semantic_ok"]
            raw.write_text(json.dumps(row) + "\n", encoding="utf-8")
            report = replay_evaluations([raw])
            self.assertFalse(report["replay_consistent"])
            self.assertEqual(report["mismatches"], 1)


class ClusterInferenceTests(unittest.TestCase):
    def test_sign_flip_uses_cluster_effects(self) -> None:
        self.assertEqual(_cluster_sign_flip_p([0.0, 0.0]), 1.0)
        self.assertEqual(_cluster_sign_flip_p([1.0, -1.0]), 1.0)
        self.assertEqual(_cluster_sign_flip_p([1.0, 1.0]), 0.5)

    def test_benjamini_hochberg_preserves_input_order(self) -> None:
        self.assertEqual(_benjamini_hochberg([0.01, 0.04, 0.03]), [0.03, 0.04, 0.04])

    def test_reliability_does_not_treat_replicates_as_cases(self) -> None:
        frame = pd.DataFrame([
            {
                "model": "model-1",
                "mode": "line_patch",
                "case_id": "case-1",
                "semantic_program_id": "program-1",
                "replicate_index": replicate,
                "provider_ok": True,
                "semantic_ok": replicate != 2,
                "response_sha256": f"response-{replicate}",
            }
            for replicate in range(3)
        ])
        outcomes, summary = reliability_tables(frame)
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(int(summary.iloc[0]["n_cases"]), 1)
        self.assertEqual(float(summary.iloc[0]["all_replicates_semantic_ok"]), 0.0)
        self.assertEqual(float(summary.iloc[0]["any_replicate_semantic_ok"]), 100.0)
        self.assertEqual(float(summary.iloc[0]["semantic_outcome_agreement"]), 0.0)

    def test_analysis_reads_gzip_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rows.jsonl.gz"
            with gzip.open(path, "wt", encoding="utf-8") as stream:
                stream.write(json.dumps({"id": 1}) + "\n")
            self.assertEqual(read_jsonl(path), [{"id": 1}])


if __name__ == "__main__":
    unittest.main()
