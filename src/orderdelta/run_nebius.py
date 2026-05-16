from __future__ import annotations

import argparse
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

DEFAULT_BASE_URL = "https://api.studio.nebius.com/v1/"


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
    for attempt in range(max_retries + 1):
        try:
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
            }
        except Exception as exc:  # noqa: BLE001 - runner records provider failures.
            last_error = repr(exc)
            if attempt < max_retries:
                time.sleep(min(30.0, 1.5 * (2**attempt)))
    return {"ok": False, "content": "", "provider_error": last_error}


def run_one(client: OpenAI, model: str, mode: str, case: dict[str, Any], max_retries: int) -> dict[str, Any]:
    result = call_model(client, model, mode, case, max_retries)
    evaluation = evaluate_text(result.get("content", ""), case, mode)
    return {
        "model": model,
        "mode": mode,
        "case": case,
        "result": result,
        "evaluation": evaluation.to_dict(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--models", nargs="+", required=True)
    parser.add_argument("--modes", nargs="+", choices=["rewrite", "line_patch"], default=["rewrite", "line_patch"])
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

    tasks = [
        (model, mode, row)
        for model in args.models
        for mode in args.modes
        for row in rows
        if (model, mode, row["id"]) not in seen
    ]
    total = len(args.models) * len(args.modes) * len(rows)
    done = len(seen)
    print(f"starting {len(tasks)} pending calls ({done}/{total} already complete)", flush=True)

    with args.out.open("a", encoding="utf-8") as f:
        with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
            futures = {
                pool.submit(run_one, client, model, mode, row, args.max_retries): (model, mode, row)
                for model, mode, row in tasks
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
