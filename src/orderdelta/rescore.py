from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .evaluate import evaluate_text


def rescore_record(record: dict[str, Any]) -> dict[str, Any]:
    result = record.get("result") or {}
    record["evaluation"] = evaluate_text(
        str(result.get("content", "")),
        record["case"],
        record["mode"],
    ).to_dict()
    record["evaluation_contract"] = "orderdelta_v3_identity_aware"
    return record


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.input.resolve() == args.out.resolve():
        raise SystemExit("refusing to overwrite the source run; choose a distinct --out path")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with args.input.open("r", encoding="utf-8") as source, args.out.open("w", encoding="utf-8") as target:
        for line in source:
            if not line.strip():
                continue
            record = rescore_record(json.loads(line))
            target.write(json.dumps(record, sort_keys=True) + "\n")
            count += 1
    print(f"rescored {count} records to {args.out}")


if __name__ == "__main__":
    main()
