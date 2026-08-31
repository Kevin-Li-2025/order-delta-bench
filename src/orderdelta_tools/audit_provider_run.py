from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def audit_runs(
    run_paths: list[Path],
    dataset_path: Path,
    catalog_path: Path,
    experiment_id: str,
    replicates: int,
    modes: list[str],
) -> dict[str, Any]:
    dataset = read_jsonl(dataset_path)
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    models = [str(row["id"]) for row in catalog["models"]]
    pricing = {str(row["id"]): row["pricing"] for row in catalog["models"]}
    case_ids = [str(row["id"]) for row in dataset]
    expected = {
        (model, mode, case_id, replicate)
        for model in models
        for mode in modes
        for case_id in case_ids
        for replicate in range(replicates)
    }
    dataset_digest = file_sha256(dataset_path)
    catalog_digest = file_sha256(catalog_path)
    seen: set[tuple[str, str, str, int]] = set()
    duplicates: list[tuple[str, str, str, int]] = []
    unexpected: list[tuple[str, str, str, int]] = []
    protocol_mismatches: list[dict[str, Any]] = []
    finish_reasons: Counter[str] = Counter()
    provider_errors: Counter[str] = Counter()
    source_digests: set[str] = set()
    generation_configs: Counter[str] = Counter()
    per_model: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "calls": 0,
            "provider_ok": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "reasoning_tokens": 0,
            "estimated_usd": 0.0,
        }
    )

    for path in run_paths:
        for row in read_jsonl(path):
            protocol = row.get("protocol") or {}
            replicate = int(protocol.get("replicate_index", -1))
            key = (str(row["model"]), str(row["mode"]), str(row["case"]["id"]), replicate)
            if key in seen:
                duplicates.append(key)
            seen.add(key)
            if key not in expected:
                unexpected.append(key)
            expected_protocol = {
                "experiment_id": experiment_id,
                "dataset_sha256": dataset_digest,
                "model_catalog_sha256": catalog_digest,
            }
            observed = {field: protocol.get(field) for field in expected_protocol}
            if observed != expected_protocol:
                protocol_mismatches.append({"key": key, "observed": observed})
            if protocol.get("source_sha256"):
                source_digests.add(str(protocol["source_sha256"]))
            generation_configs[json.dumps(protocol.get("generation_config"), sort_keys=True)] += 1

            result = row.get("result") or {}
            usage = result.get("usage") or {}
            model = str(row["model"])
            summary = per_model[model]
            summary["calls"] += 1
            summary["provider_ok"] += int(bool(result.get("ok")))
            prompt_tokens = int(usage.get("prompt_tokens") or 0)
            completion_tokens = int(usage.get("completion_tokens") or 0)
            reasoning_tokens = int(
                (usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0
            )
            summary["prompt_tokens"] += prompt_tokens
            summary["completion_tokens"] += completion_tokens
            summary["reasoning_tokens"] += reasoning_tokens
            if model in pricing:
                summary["estimated_usd"] += (
                    prompt_tokens * float(pricing[model]["prompt"])
                    + completion_tokens * float(pricing[model]["completion"])
                )
            finish_reasons[f"{model}|{row['mode']}|{result.get('finish_reason')}"] += 1
            if not result.get("ok"):
                provider_errors[f"{model}|{row['mode']}|{result.get('provider_error')}"] += 1

    missing = sorted(expected - seen)
    structurally_complete = (
        not missing
        and not duplicates
        and not unexpected
        and not protocol_mismatches
        and len(source_digests) == 1
        and len(generation_configs) == 1
    )
    return {
        "experiment_id": experiment_id,
        "dataset": {
            "path": str(dataset_path),
            "sha256": dataset_digest,
            "cases": len(case_ids),
        },
        "model_catalog": {
            "path": str(catalog_path),
            "sha256": catalog_digest,
            "models": models,
        },
        "modes": modes,
        "replicates": replicates,
        "expected_calls": len(expected),
        "observed_unique_calls": len(seen),
        "missing_calls": len(missing),
        "missing_examples": missing[:50],
        "duplicate_calls": len(duplicates),
        "duplicate_examples": duplicates[:50],
        "unexpected_calls": len(unexpected),
        "unexpected_examples": unexpected[:50],
        "protocol_mismatches": len(protocol_mismatches),
        "protocol_mismatch_examples": protocol_mismatches[:50],
        "source_sha256_values": sorted(source_digests),
        "generation_configs": dict(sorted(generation_configs.items())),
        "finish_reasons": dict(sorted(finish_reasons.items())),
        "provider_errors": sum(provider_errors.values()),
        "provider_error_groups": dict(sorted(provider_errors.items())),
        "per_model": {model: per_model[model] for model in sorted(per_model)},
        "estimated_usd": sum(float(row["estimated_usd"]) for row in per_model.values()),
        "raw_files": [
            {"path": str(path), "sha256": file_sha256(path), "bytes": path.stat().st_size}
            for path in run_paths
        ],
        "structurally_complete": structurally_complete,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", nargs="+", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--model-catalog", type=Path, required=True)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--replicates", type=int, required=True)
    parser.add_argument(
        "--modes",
        nargs="+",
        default=["rewrite_with_ids", "line_patch", "json_patch"],
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()

    report = audit_runs(
        args.runs,
        args.dataset,
        args.model_catalog,
        args.experiment_id,
        args.replicates,
        args.modes,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.out.with_suffix(args.out.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(args.out)
    print(
        f"observed {report['observed_unique_calls']}/{report['expected_calls']} calls; "
        f"provider errors={report['provider_errors']}; estimated_usd={report['estimated_usd']:.4f}"
    )
    if args.require_complete and not report["structurally_complete"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
