from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from openai import OpenAI

from .contracts import RESPONSE_FORMATS
from .evaluate import evaluate_text
from .prompts import SYSTEM_PROMPT, build_user_prompt

DEFAULT_BASE_URL = "https://api.tokenfactory.nebius.com/v1/"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_seen(path: Path) -> set[tuple[str, str, str]]:
    if not path.exists():
        return set()
    seen = set()
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            seen.add((row["model"], row["mode"], row["case"]["id"]))
    return seen


def select_cases(rows: list[dict[str, Any]], limit_per_category: int | None, seed: int) -> list[dict[str, Any]]:
    if limit_per_category is None:
        return rows
    rng = random.Random(seed)
    buckets: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        buckets.setdefault(row["category"], []).append(row)
    selected = []
    for category in sorted(buckets):
        bucket = list(buckets[category])
        rng.shuffle(bucket)
        selected.extend(bucket[:limit_per_category])
    selected.sort(key=lambda row: (row["category"], row["id"]))
    return selected


def call_model(
    client: OpenAI,
    model: str,
    mode: str,
    case: dict[str, Any],
    max_retries: int,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(case, mode)},
        ],
        "temperature": 0,
        "max_tokens": 900,
        "response_format": RESPONSE_FORMATS[mode],
    }
    last_error = None
    first_submitted_at = dt.datetime.now(dt.timezone.utc).isoformat()
    for attempt in range(max_retries + 1):
        try:
            submitted_at = dt.datetime.now(dt.timezone.utc).isoformat()
            started = time.time()
            response = client.chat.completions.create(**kwargs)
            elapsed = time.time() - started
            message = response.choices[0].message
            return {
                "ok": True,
                "content": message.content or "",
                "finish_reason": response.choices[0].finish_reason,
                "usage": response.usage.model_dump() if response.usage else None,
                "latency_s": elapsed,
                "provider_request_id": getattr(response, "id", None),
                "provider_model": getattr(response, "model", None),
                "model_fingerprint": getattr(response, "system_fingerprint", None),
                "submission_timestamp": submitted_at,
                "response_timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
                "retry_attempt": attempt,
                "schema_enforcement_mode": "strict_json_schema",
            }
        except Exception as exc:  # noqa: BLE001 - runner records provider failures.
            last_error = repr(exc)
            if attempt < max_retries:
                time.sleep(min(30.0, 1.5 * (2**attempt)))
    return {
        "ok": False,
        "content": "",
        "provider_error": last_error,
        "submission_timestamp": first_submitted_at,
        "response_timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        "retry_attempt": max_retries,
        "schema_enforcement_mode": "strict_json_schema",
    }


def run_one(
    client: OpenAI,
    model: str,
    mode: str,
    case: dict[str, Any],
    max_retries: int,
    condition_order: list[str],
) -> dict[str, Any]:
    result = call_model(client, model, mode, case, max_retries)
    evaluation = evaluate_text(result.get("content", ""), case, mode)
    return {
        "model": model,
        "mode": mode,
        "case": case,
        "protocol": {
            "pair_id": f"{model}:{case['id']}",
            "condition_order": condition_order,
            "condition_position": condition_order.index(mode),
        },
        "result": result,
        "evaluation": evaluation.to_dict(),
    }


def counterbalanced_tasks(
    models: list[str],
    modes: list[str],
    rows: list[dict[str, Any]],
    seen: set[tuple[str, str, str]],
    seed: int,
) -> list[tuple[str, str, dict[str, Any], list[str]]]:
    tasks: list[tuple[str, str, dict[str, Any], list[str]]] = []
    for model in models:
        for row in rows:
            digest = hashlib.sha256(f"{seed}:{model}:{row['id']}".encode()).digest()
            offset = int.from_bytes(digest[:4], "big") % len(modes)
            condition_order = modes[offset:] + modes[:offset]
            if digest[4] % 2:
                condition_order = list(reversed(condition_order))
            for mode in condition_order:
                if (model, mode, row["id"]) not in seen:
                    tasks.append((model, mode, row, condition_order))
    return tasks


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--models", nargs="+", required=True)
    parser.add_argument(
        "--modes",
        nargs="+",
        choices=["rewrite", "rewrite_with_ids", "line_patch", "json_patch"],
        default=["rewrite_with_ids", "line_patch", "json_patch"],
    )
    parser.add_argument("--limit-per-category", type=int)
    parser.add_argument("--seed", type=int, default=20260516)
    parser.add_argument("--base-url", default=os.environ.get("NEBIUS_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--request-timeout", type=float, default=90.0)
    parser.add_argument("--progress-every", type=int, default=1)
    args = parser.parse_args()

    api_key = os.environ.get("NEBIUS_API_KEY")
    if not api_key:
        raise SystemExit("NEBIUS_API_KEY is required but was not found in the environment.")

    rows = select_cases(read_jsonl(args.dataset), args.limit_per_category, args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    seen = load_seen(args.out)
    client = OpenAI(base_url=args.base_url, api_key=api_key, timeout=args.request_timeout)
    lock = threading.Lock()

    tasks = counterbalanced_tasks(args.models, args.modes, rows, seen, args.seed)
    total = len(args.models) * len(args.modes) * len(rows)
    selected_keys = {(model, mode, row["id"]) for model in args.models for mode in args.modes for row in rows}
    done = len(seen & selected_keys)
    print(f"starting {len(tasks)} pending calls ({done}/{total} already complete)", flush=True)

    with args.out.open("a", encoding="utf-8") as f, ThreadPoolExecutor(
        max_workers=max(1, args.concurrency)
    ) as pool:
        futures = {
            pool.submit(run_one, client, model, mode, row, args.max_retries, condition_order): (model, mode, row)
            for model, mode, row, condition_order in tasks
        }
        for future in as_completed(futures):
            model, mode, row = futures[future]
            record = future.result()
            with lock:
                done += 1
                status = "ok" if record["result"].get("ok") else "provider_error"
                semantic = record["evaluation"].get("semantic_ok")
                should_print = args.progress_every <= 1 or done % args.progress_every == 0 or status != "ok"
                if should_print:
                    print(f"[{done}/{total}] {model} {mode} {row['id']} {status} semantic={semantic}", flush=True)
                f.write(json.dumps(record, sort_keys=True) + "\n")
                f.flush()


if __name__ == "__main__":
    main()
