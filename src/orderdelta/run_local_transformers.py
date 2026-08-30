from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import platform
import time
from pathlib import Path
from typing import Any

from .evaluate import evaluate_text
from .prompts import SYSTEM_PROMPT, build_user_prompt


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def select_cases(rows: list[dict[str, Any]], limit_per_category: int, seed: int) -> list[dict[str, Any]]:
    import random

    rng = random.Random(seed)
    buckets: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        buckets.setdefault(row["category"], []).append(row)
    selected = []
    for category in sorted(buckets):
        bucket = list(buckets[category])
        rng.shuffle(bucket)
        selected.extend(bucket[:limit_per_category])
    return sorted(selected, key=lambda row: (row["category"], row["id"]))


def _condition_order(modes: list[str], case_id: str, seed: int) -> list[str]:
    digest = hashlib.sha256(f"{seed}:{case_id}".encode()).digest()
    offset = int.from_bytes(digest[:4], "big") % len(modes)
    order = modes[offset:] + modes[:offset]
    return list(reversed(order)) if digest[4] % 2 else order


def _runtime_manifest(torch: Any, transformers: Any, model_path: Path) -> dict[str, Any]:
    digests = {}
    for filename in ("config.json", "tokenizer_config.json", "model.safetensors.index.json"):
        path = model_path / filename
        if path.exists():
            digests[filename] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "hostname": platform.node(),
        "python": platform.python_version(),
        "torch": torch.__version__,
        "transformers": transformers.__version__,
        "cuda": torch.version.cuda,
        "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "gpu_capability": list(torch.cuda.get_device_capability(0)) if torch.cuda.is_available() else None,
        "compiled_cuda_arches": torch.cuda.get_arch_list() if torch.cuda.is_available() else [],
        "model_path": str(model_path),
        "model_metadata_sha256": digests,
        "schema_enforcement_mode": "prompt_only_unconstrained",
        "evidence_level": "single_model_single_trial_engineering_pilot",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--model-id", default="local-model")
    parser.add_argument(
        "--modes",
        nargs="+",
        choices=["rewrite", "rewrite_with_ids", "line_patch", "json_patch"],
        default=["rewrite_with_ids", "line_patch", "json_patch"],
    )
    parser.add_argument("--limit-per-category", type=int, default=1)
    parser.add_argument("--seed", type=int, default=20260831)
    parser.add_argument("--max-new-tokens", type=int, default=700)
    args = parser.parse_args()

    import torch
    import transformers
    from transformers import AutoModelForCausalLM, AutoTokenizer

    if not torch.cuda.is_available():
        raise SystemExit("CUDA is required for the local GPU pilot")
    capability = torch.cuda.get_device_capability(0)
    required_arch = f"sm_{capability[0]}{capability[1]}"
    if required_arch not in torch.cuda.get_arch_list():
        raise SystemExit(
            f"PyTorch runtime does not contain {required_arch}; compiled arches: {torch.cuda.get_arch_list()}"
        )
    torch.manual_seed(args.seed)
    tokenizer = AutoTokenizer.from_pretrained(args.model_path, local_files_only=True)
    model = AutoModelForCausalLM.from_pretrained(
        args.model_path,
        dtype="auto",
        device_map="cuda",
        local_files_only=True,
        attn_implementation="sdpa",
    )
    model.eval()
    runtime = _runtime_manifest(torch, transformers, args.model_path)

    cases = select_cases(read_jsonl(args.dataset), args.limit_per_category, args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    seen: set[tuple[str, str]] = set()
    if args.out.exists():
        for line in args.out.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                seen.add((row["mode"], row["case"]["id"]))

    total = len(cases) * len(args.modes)
    completed = len(seen)
    with args.out.open("a", encoding="utf-8") as handle:
        for case in cases:
            condition_order = _condition_order(args.modes, case["id"], args.seed)
            for mode in condition_order:
                if (mode, case["id"]) in seen:
                    continue
                messages = [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": build_user_prompt(case, mode)},
                ]
                prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
                inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
                submitted_at = dt.datetime.now(dt.timezone.utc).isoformat()
                started = time.perf_counter()
                with torch.inference_mode():
                    output = model.generate(
                        **inputs,
                        max_new_tokens=args.max_new_tokens,
                        do_sample=False,
                        pad_token_id=tokenizer.eos_token_id,
                    )
                elapsed = time.perf_counter() - started
                generated = output[0, inputs["input_ids"].shape[1] :]
                content = tokenizer.decode(generated, skip_special_tokens=True)
                evaluation = evaluate_text(content, case, mode)
                record = {
                    "model": args.model_id,
                    "mode": mode,
                    "case": case,
                    "protocol": {
                        "pair_id": f"{args.model_id}:{case['id']}",
                        "condition_order": condition_order,
                        "condition_position": condition_order.index(mode),
                    },
                    "runtime": runtime,
                    "result": {
                        "ok": True,
                        "content": content,
                        "latency_s": elapsed,
                        "submission_timestamp": submitted_at,
                        "response_timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
                        "usage": {
                            "prompt_tokens": int(inputs["input_ids"].shape[1]),
                            "completion_tokens": int(generated.shape[0]),
                            "total_tokens": int(inputs["input_ids"].shape[1] + generated.shape[0]),
                        },
                        "schema_enforcement_mode": "prompt_only_unconstrained",
                    },
                    "evaluation": evaluation.to_dict(),
                }
                handle.write(json.dumps(record, sort_keys=True) + "\n")
                handle.flush()
                completed += 1
                print(
                    f"[{completed}/{total}] {mode} {case['id']} "
                    f"schema={evaluation.schema_valid} semantic={evaluation.semantic_ok} {elapsed:.2f}s",
                    flush=True,
                )


if __name__ == "__main__":
    main()
