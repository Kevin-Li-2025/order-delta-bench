from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from src.orderdelta.evaluate import evaluate_text
from src.orderdelta_tools.audit_provider_run import read_jsonl


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def replay_evaluations(run_paths: list[Path]) -> dict[str, Any]:
    records = 0
    mismatches: list[dict[str, Any]] = []
    contracts: Counter[str] = Counter()
    for path in run_paths:
        for row in read_jsonl(path):
            records += 1
            result = row.get("result") or {}
            replayed = evaluate_text(
                str(result.get("content", "")),
                row["case"],
                str(row["mode"]),
            ).to_dict()
            recorded = row.get("evaluation") or {}
            contracts[str(row.get("evaluation_contract"))] += 1
            if canonical_sha256(recorded) != canonical_sha256(replayed):
                mismatches.append({
                    "path": str(path),
                    "model": row.get("model"),
                    "mode": row.get("mode"),
                    "case_id": (row.get("case") or {}).get("id"),
                    "replicate_index": (row.get("protocol") or {}).get("replicate_index"),
                    "recorded_sha256": canonical_sha256(recorded),
                    "replayed_sha256": canonical_sha256(replayed),
                })
    return {
        "records": records,
        "evaluation_contracts": dict(sorted(contracts.items())),
        "mismatches": len(mismatches),
        "mismatch_examples": mismatches[:50],
        "replay_consistent": not mismatches,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", nargs="+", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    report = replay_evaluations(args.runs)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.out.with_suffix(args.out.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(args.out)
    print(
        f"replayed {report['records']} evaluations; mismatches={report['mismatches']}"
    )
    if not report["replay_consistent"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
