from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import random
from pathlib import Path
from typing import Any

import pandas as pd

METRICS = [
    "json_valid",
    "schema_valid",
    "status_correct",
    "order_exact",
    "constraints_exact",
    "state_preserved_when_blocked",
    "semantic_ok",
    "unsafe_state_change",
    "unintended_drift",
    "identity_error",
    "identity_observable",
    "identity_fidelity",
    "operation_executable",
]

CONTINUOUS_METRICS = [
    "authorized_write_precision",
    "authorized_write_recall",
    "collateral_write_count",
]

TAXONOMY = [
    "unsafe_state_change",
    "unintended_drift",
    "identity_error",
    "status_error",
    "order_error",
    "constraint_error",
    "operation_error",
]

MODEL_LABELS = {
    "Qwen/Qwen3-235B-A22B-Instruct-2507": "Qwen3-235B-A22B",
    "Qwen/Qwen3-32B": "Qwen3-32B",
    "Qwen/Qwen3.5-397B-A17B-fast": "Qwen3.5-397B-fast",
    "openai/gpt-oss-120b-fast": "gpt-oss-120b-fast",
    "openai/gpt-oss-120b": "gpt-oss-120b",
    "NousResearch/Hermes-4-70B": "Hermes-4-70B",
    "NousResearch/Hermes-4-405B": "Hermes-4-405B",
    "nvidia/Cosmos3-Super-Reasoner": "Cosmos3-Super-Reasoner",
    "zai-org/GLM-5.1": "GLM-5.1",
    "Qwen/Qwen3-30B-A3B-Instruct-2507": "Qwen3-30B-A3B",
    "meta-llama/Llama-3.3-70B-Instruct": "Llama-3.3-70B",
    "meta-llama/Meta-Llama-3.1-8B-Instruct": "Llama-3.1-8B",
    "google/gemma-3-27b-it": "Gemma-3-27B",
    "google/gemma-2-2b-it": "Gemma-2-2B",
    "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B": "Nemotron-3-Nano-30B",
    "nvidia/Llama-3_1-Nemotron-Ultra-253B-v1": "Nemotron-Ultra-253B",
    "deepseek-ai/DeepSeek-V3.2-fast": "DeepSeek-V3.2-fast",
}

MODEL_ORDER = [
    "Qwen/Qwen3-235B-A22B-Instruct-2507",
    "Qwen/Qwen3-32B",
    "openai/gpt-oss-120b",
    "NousResearch/Hermes-4-70B",
    "NousResearch/Hermes-4-405B",
    "nvidia/Cosmos3-Super-Reasoner",
    "zai-org/GLM-5.1",
    "Qwen/Qwen3.5-397B-A17B-fast",
    "openai/gpt-oss-120b-fast",
    "Qwen/Qwen3-30B-A3B-Instruct-2507",
    "meta-llama/Llama-3.3-70B-Instruct",
    "meta-llama/Meta-Llama-3.1-8B-Instruct",
    "google/gemma-3-27b-it",
    "google/gemma-2-2b-it",
    "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
    "nvidia/Llama-3_1-Nemotron-Ultra-253B-v1",
    "deepseek-ai/DeepSeek-V3.2-fast",
]

CATEGORY_ORDER = [
    "add_item",
    "remove_scoped_duplicate",
    "quantity_increase",
    "quantity_decrease",
    "modifier_add_scoped",
    "modifier_reversal",
    "size_change_scoped",
    "replace_item",
    "constraint_add_safe",
    "constraint_new_conflict",
    "unavailable_add",
    "stale_reference",
]

CATEGORY_LABELS = {
    "add_item": "add item",
    "remove_scoped_duplicate": "remove duplicate",
    "quantity_increase": "qty increase",
    "quantity_decrease": "qty decrease",
    "modifier_add_scoped": "scoped add-on",
    "modifier_reversal": "modifier reversal",
    "size_change_scoped": "scoped size",
    "replace_item": "replace item",
    "constraint_add_safe": "safe constraint",
    "constraint_new_conflict": "new conflict",
    "unavailable_add": "unavailable edit",
    "stale_reference": "stale reference",
}

MODE_LABELS = {
    "rewrite": "legacy rewrite (ID-free)",
    "rewrite_with_ids": "rewrite + IDs",
    "line_patch": "typed line patch",
    "json_patch": "JSON Patch",
}

MODE_ORDER = {"rewrite": 0, "rewrite_with_ids": 1, "line_patch": 2, "json_patch": 3}


def model_label(model: str) -> str:
    return MODEL_LABELS.get(model, model.split("/")[-1])


def category_label(category: str) -> str:
    return CATEGORY_LABELS.get(category, category)


def latex_escape(value: str) -> str:
    """Escape identifiers without backslashes inside f-string expressions."""
    return value.replace("_", "\\_")


def pct(x: pd.Series) -> float:
    return float(x.mean() * 100)


def semantic_program_id(case: dict[str, Any]) -> str:
    if case.get("semantic_program_id"):
        return str(case["semantic_program_id"])
    try:
        lexicalization = int(str(case["id"]).rsplit("_", 1)[-1])
    except (KeyError, ValueError):
        return str(case.get("id", "unknown"))
    return f"{case.get('category', 'unknown')}:template-{lexicalization % 8:02d}"


def classify_errors(ev: dict[str, Any]) -> dict[str, bool]:
    semantic_ok = bool(ev.get("semantic_ok", False))
    return {
        "unsafe_state_change": bool(ev.get("unsafe_state_change", False)),
        "unintended_drift": bool(ev.get("unintended_drift", False)),
        "identity_error": bool(ev.get("identity_error", False)),
        "status_error": not semantic_ok and not bool(ev.get("status_correct", False)),
        "order_error": not semantic_ok and not bool(ev.get("order_exact", False)),
        "constraint_error": not semantic_ok and not bool(ev.get("constraints_exact", False)),
        "operation_error": not bool(ev.get("operation_executable", True)),
    }


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            return [json.loads(line) for line in stream if line.strip()]
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def read_runs(
    paths: list[Path],
    pricing: dict[str, dict[str, float]] | None = None,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    rows_by_key: dict[tuple[str, str, str, int], dict[str, Any]] = {}
    raw_rows: list[dict[str, Any]] = []
    for path in paths:
        for raw in read_jsonl(path):
            ev = raw["evaluation"]
            result = raw["result"]
            replicate_index = int((raw.get("protocol") or {}).get("replicate_index", 0))
            identity_observable = bool(ev.get("identity_observable", raw.get("mode") != "rewrite"))
            usage = result.get("usage") or {}
            prompt_tokens = usage.get("prompt_tokens")
            completion_tokens = usage.get("completion_tokens")
            model_pricing = (pricing or {}).get(str(raw["model"]))
            estimated_cost_usd = None
            if model_pricing and prompt_tokens is not None and completion_tokens is not None:
                estimated_cost_usd = (
                    int(prompt_tokens) * model_pricing["prompt"]
                    + int(completion_tokens) * model_pricing["completion"]
                )
            content = str(result.get("content", ""))
            record = {
                "model": raw["model"],
                "mode": raw["mode"],
                "case_id": raw["case"]["id"],
                "replicate_index": replicate_index,
                "category": raw["case"]["category"],
                "semantic_program_id": semantic_program_id(raw["case"]),
                "template_family_id": raw["case"].get("template_family_id") or semantic_program_id(raw["case"]),
                "provider_ok": result.get("ok", False),
                "latency_s": result.get("latency_s"),
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "estimated_cost_usd": estimated_cost_usd,
                "response_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                **{
                    metric: (
                        None
                        if metric in {"identity_error", "identity_fidelity"} and not identity_observable
                        else None
                        if metric == "state_preserved_when_blocked"
                        and raw["case"].get("expected_status") == "accepted"
                        else bool(ev.get(metric, False))
                    )
                    for metric in METRICS
                },
                "identity_observable": identity_observable,
                **{metric: ev.get(metric) for metric in CONTINUOUS_METRICS},
                **classify_errors(ev),
                "error": ev.get("error") or result.get("provider_error"),
            }
            rows_by_key[(
                record["model"],
                record["mode"],
                record["case_id"],
                replicate_index,
            )] = record
            raw_rows.append(raw)
    return pd.DataFrame(rows_by_key.values()), raw_rows


def write_main_table(df: pd.DataFrame, out: Path) -> None:
    summary = (
        df.groupby(["model", "mode"], dropna=False)
        .agg(
            n=("case_id", "count"),
            provider_ok=("provider_ok", pct),
            schema_valid=("schema_valid", pct),
            semantic_ok=("semantic_ok", pct),
            unsafe_state_change=("unsafe_state_change", pct),
            unintended_drift=("unintended_drift", pct),
            identity_error=("identity_error", pct),
        )
        .reset_index()
    )
    summary["model_order"] = summary["model"].apply(lambda m: MODEL_ORDER.index(m) if m in MODEL_ORDER else 99)
    summary["mode_order"] = summary["mode"].map(MODE_ORDER).fillna(99)
    summary = summary.sort_values(["model_order", "mode_order"])
    lines = [
        "\\begin{tabular}{llrrrrrrr}",
        "\\toprule",
        "Model & Interface & $n$ & Provider & Schema & Semantic & Unsafe & Drift & Identity \\\\",
        "\\midrule",
    ]
    for _, row in summary.iterrows():
        lines.append(
            f"{latex_escape(model_label(str(row['model'])))} & "
            f"{latex_escape(MODE_LABELS.get(str(row['mode']), str(row['mode'])))} & "
            f"{int(row['n'])} & {row['provider_ok']:.1f} & {row['schema_valid']:.1f} & "
            f"{row['semantic_ok']:.1f} & {row['unsafe_state_change']:.1f} & "
            f"{row['unintended_drift']:.1f} & {row['identity_error']:.1f} \\\\"
        )
    lines.extend(["\\bottomrule", "\\end{tabular}", ""])
    out.write_text("\n".join(lines), encoding="utf-8")


def write_category_table(df: pd.DataFrame, out: Path) -> None:
    table = (
        df.groupby(["category", "mode"], dropna=False)
        .agg(n=("case_id", "count"), semantic_ok=("semantic_ok", pct), unsafe_state_change=("unsafe_state_change", pct))
        .reset_index()
    )
    table["category_order"] = table["category"].apply(lambda c: CATEGORY_ORDER.index(c) if c in CATEGORY_ORDER else 99)
    table["mode_order"] = table["mode"].map(MODE_ORDER).fillna(99)
    table = table.sort_values(["category_order", "mode_order"])
    lines = [
        "\\begin{tabular}{llrrr}",
        "\\toprule",
        "Category & Interface & $n$ & Semantic & Unsafe \\\\",
        "\\midrule",
    ]
    for _, row in table.iterrows():
        lines.append(
            f"{latex_escape(category_label(str(row['category'])))} & "
            f"{latex_escape(MODE_LABELS.get(str(row['mode']), str(row['mode'])))} & "
            f"{int(row['n'])} & {row['semantic_ok']:.1f} & {row['unsafe_state_change']:.1f} \\\\"
        )
    lines.extend(["\\bottomrule", "\\end{tabular}", ""])
    out.write_text("\n".join(lines), encoding="utf-8")


def write_taxonomy_table(df: pd.DataFrame, out: Path) -> None:
    table = (
        df.groupby(["mode"], dropna=False)
        .agg(n=("case_id", "count"), **{col: (col, pct) for col in TAXONOMY})
        .reset_index()
        .sort_values("mode")
    )
    lines = [
        "\\begin{tabular}{lrrrrrrrr}",
        "\\toprule",
        "Interface & $n$ & Unsafe & Drift & Identity & Status & Order & Constraint & Operation \\\\",
        "\\midrule",
    ]
    for _, row in table.iterrows():
        values = " & ".join(f"{row[col]:.1f}" for col in TAXONOMY)
        lines.append(f"{MODE_LABELS.get(str(row['mode']), str(row['mode']))} & {int(row['n'])} & {values} \\\\")
    lines.extend(["\\bottomrule", "\\end{tabular}", ""])
    out.write_text("\n".join(lines), encoding="utf-8")


def _bootstrap_diff_ci(rewrite: list[bool], patch: list[bool], n_boot: int = 10000) -> tuple[float, float, float]:
    rng = random.Random(20260516)
    n = len(rewrite)
    diffs: list[float] = []
    for _ in range(n_boot):
        total = 0
        for _ in range(n):
            idx = rng.randrange(n)
            total += int(patch[idx]) - int(rewrite[idx])
        diffs.append(100.0 * total / n)
    diffs.sort()
    observed = 100.0 * (sum(patch) - sum(rewrite)) / n
    return observed, diffs[int(0.025 * n_boot)], diffs[int(0.975 * n_boot)]


def _mcnemar_exact_p(rewrite: list[bool], patch: list[bool]) -> tuple[int, int, float]:
    rewrite_only = sum(1 for r, p in zip(rewrite, patch) if r and not p)
    patch_only = sum(1 for r, p in zip(rewrite, patch) if p and not r)
    n = rewrite_only + patch_only
    if n == 0:
        return rewrite_only, patch_only, 1.0
    k = min(rewrite_only, patch_only)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / (2**n)
    return rewrite_only, patch_only, min(1.0, 2 * tail)


def paired_stats(df: pd.DataFrame, metric: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for model, group in df.groupby("model"):
        pivot = group.pivot(index=["case_id", "replicate_index"], columns="mode", values=metric)
        if {"rewrite", "line_patch"} - set(pivot.columns):
            continue
        pivot = pivot.dropna(subset=["rewrite", "line_patch"])
        rewrite = [bool(v) for v in pivot["rewrite"].tolist()]
        patch = [bool(v) for v in pivot["line_patch"].tolist()]
        diff, lo, hi = _bootstrap_diff_ci(rewrite, patch)
        rewrite_only, patch_only, p = _mcnemar_exact_p(rewrite, patch)
        rows.append({
            "model": model,
            "metric": metric,
            "n": len(rewrite),
            "rewrite_rate": 100.0 * sum(rewrite) / len(rewrite),
            "line_patch_rate": 100.0 * sum(patch) / len(patch),
            "diff_patch_minus_rewrite": diff,
            "ci_low": lo,
            "ci_high": hi,
            "rewrite_only_successes": rewrite_only,
            "patch_only_successes": patch_only,
            "mcnemar_p": p,
        })
    if not rows:
        return pd.DataFrame(columns=[
            "model", "metric", "n", "rewrite_rate", "line_patch_rate",
            "diff_patch_minus_rewrite", "ci_low", "ci_high",
            "rewrite_only_successes", "patch_only_successes", "mcnemar_p",
        ])
    return pd.DataFrame(rows).sort_values(["metric", "model"])


CONTROLLED_COMPARISONS = [
    ("rewrite", "rewrite_with_ids", "stable_id_effect"),
    ("rewrite_with_ids", "line_patch", "rewrite_ids_vs_typed_patch"),
    ("rewrite_with_ids", "json_patch", "rewrite_ids_vs_json_patch"),
    ("line_patch", "json_patch", "typed_patch_vs_json_patch"),
]


def _cluster_bootstrap_ci(cluster_diffs: list[float], n_boot: int = 10000) -> tuple[float, float, float]:
    if not cluster_diffs:
        return 0.0, 0.0, 0.0
    rng = random.Random(20260831)
    n = len(cluster_diffs)
    samples = []
    for _ in range(n_boot):
        samples.append(100.0 * sum(cluster_diffs[rng.randrange(n)] for _ in range(n)) / n)
    samples.sort()
    observed = 100.0 * sum(cluster_diffs) / n
    return observed, samples[int(0.025 * n_boot)], samples[int(0.975 * n_boot)]


def _cluster_sign_flip_p(cluster_diffs: list[float], n_permutations: int = 20000) -> float:
    nonzero = [value for value in cluster_diffs if abs(value) > 1e-12]
    if not nonzero:
        return 1.0
    observed = abs(sum(nonzero))
    if len(nonzero) <= 20:
        extreme = 0
        total = 1 << len(nonzero)
        for mask in range(total):
            candidate = sum(
                value if mask & (1 << index) else -value
                for index, value in enumerate(nonzero)
            )
            if abs(candidate) >= observed - 1e-12:
                extreme += 1
        return extreme / total
    rng = random.Random(20260831)
    extreme = 0
    for _ in range(n_permutations):
        candidate = sum(value if rng.getrandbits(1) else -value for value in nonzero)
        if abs(candidate) >= observed - 1e-12:
            extreme += 1
    return (extreme + 1) / (n_permutations + 1)


def _benjamini_hochberg(p_values: list[float]) -> list[float]:
    if not p_values:
        return []
    adjusted = [1.0] * len(p_values)
    running_min = 1.0
    ordered = sorted(enumerate(p_values), key=lambda item: item[1], reverse=True)
    total = len(p_values)
    for reverse_rank, (index, p_value) in enumerate(ordered, start=1):
        rank = total - reverse_rank + 1
        running_min = min(running_min, float(p_value) * total / rank)
        adjusted[index] = min(1.0, running_min)
    return adjusted


def cluster_paired_stats(df: pd.DataFrame, metric: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    available_modes = set(df["mode"])
    comparisons = [item for item in CONTROLLED_COMPARISONS if {item[0], item[1]} <= available_modes]
    if {"rewrite", "line_patch"} <= available_modes:
        comparisons.append(("rewrite", "line_patch", "legacy_confounded_comparison"))
    for model, group in df.groupby("model"):
        for mode_a, mode_b, comparison in comparisons:
            subset = group[group["mode"].isin([mode_a, mode_b])]
            pivot = subset.pivot(
                index=["case_id", "replicate_index"], columns="mode", values=metric
            )
            if {mode_a, mode_b} - set(pivot.columns):
                continue
            pivot = pivot.dropna(subset=[mode_a, mode_b])
            if pivot.empty:
                continue
            cluster_lookup = (
                subset.drop_duplicates(["case_id", "replicate_index"])
                .set_index(["case_id", "replicate_index"])["semantic_program_id"]
            )
            pivot["cluster"] = [cluster_lookup.loc[pair_id] for pair_id in pivot.index]
            pivot["diff"] = pivot[mode_b].astype(float) - pivot[mode_a].astype(float)
            cluster_diffs = pivot.groupby("cluster")["diff"].mean().tolist()
            diff, lo, hi = _cluster_bootstrap_ci(cluster_diffs)
            a_values = [bool(value) for value in pivot[mode_a].tolist()]
            b_values = [bool(value) for value in pivot[mode_b].tolist()]
            a_only, b_only, p_value = _mcnemar_exact_p(a_values, b_values)
            cluster_p_value = _cluster_sign_flip_p(cluster_diffs)
            rows.append({
                "model": model,
                "metric": metric,
                "comparison": comparison,
                "mode_a": mode_a,
                "mode_b": mode_b,
                "n_cases": len(pivot),
                "n_clusters": len(cluster_diffs),
                "cluster_unit": "semantic_program_id",
                "mode_a_rate": 100.0 * sum(a_values) / len(a_values),
                "mode_b_rate": 100.0 * sum(b_values) / len(b_values),
                "diff_b_minus_a": diff,
                "cluster_ci_low": lo,
                "cluster_ci_high": hi,
                "mode_a_only_successes": a_only,
                "mode_b_only_successes": b_only,
                "case_level_mcnemar_p_descriptive": p_value,
                "cluster_sign_flip_p": cluster_p_value,
            })
    return pd.DataFrame(rows)


def write_paired_table(stats: pd.DataFrame, out: Path) -> None:
    metric_labels = {
        "semantic_ok": "Semantic",
        "unsafe_state_change": "Unsafe",
        "unintended_drift": "Drift",
    }
    table = stats[stats["metric"].isin(metric_labels)].copy()
    table["model_order"] = table["model"].apply(lambda m: MODEL_ORDER.index(m) if m in MODEL_ORDER else 99)
    table["metric_order"] = table["metric"].map({m: i for i, m in enumerate(metric_labels)})
    table = table.sort_values(["model_order", "metric_order"])
    lines = [
        "\\begin{tabular}{llrrrr}",
        "\\toprule",
        "Model & Metric & Rewrite & Patch & $\\Delta$ [95\\% CI] & $p$ \\\\",
        "\\midrule",
    ]
    for _, row in table.iterrows():
        p_value = "<.001" if row["mcnemar_p"] < 0.001 else f"{row['mcnemar_p']:.3f}"
        lines.append(
            f"{latex_escape(model_label(str(row['model'])))} & {metric_labels[str(row['metric'])]} & "
            f"{row['rewrite_rate']:.1f} & {row['line_patch_rate']:.1f} & "
            f"{row['diff_patch_minus_rewrite']:+.1f} "
            f"[{row['ci_low']:+.1f}, {row['ci_high']:+.1f}] & {p_value} \\\\"
        )
    lines.extend(["\\bottomrule", "\\end{tabular}", ""])
    out.write_text("\n".join(lines), encoding="utf-8")


def write_controlled_paired_table(stats: pd.DataFrame, out: Path) -> None:
    metric_labels = {
        "semantic_ok": "Semantic",
        "unsafe_state_change": "Unsafe",
        "unintended_drift": "Drift",
    }
    table = stats[
        (stats["comparison"] == "rewrite_ids_vs_typed_patch")
        & stats["metric"].isin(metric_labels)
    ].copy()
    table["model_order"] = table["model"].apply(
        lambda model: MODEL_ORDER.index(model) if model in MODEL_ORDER else 99
    )
    table["metric_order"] = table["metric"].map(
        {metric: index for index, metric in enumerate(metric_labels)}
    )
    table = table.sort_values(["model_order", "metric_order"])
    lines = [
        "\\begin{tabular}{llrrrrr}",
        "\\toprule",
        "Model & Metric & Rewrite+IDs & Typed patch & $\\Delta$ [95\\% cluster CI] & $p$ & BH $q$ \\\\",
        "\\midrule",
    ]
    for _, row in table.iterrows():
        p_value = "<.001" if row["cluster_sign_flip_p"] < 0.001 else f"{row['cluster_sign_flip_p']:.3f}"
        q_value = "<.001" if row["cluster_sign_flip_q_bh"] < 0.001 else f"{row['cluster_sign_flip_q_bh']:.3f}"
        lines.append(
            f"{latex_escape(model_label(str(row['model'])))} & "
            f"{metric_labels[str(row['metric'])]} & "
            f"{row['mode_a_rate']:.1f} & {row['mode_b_rate']:.1f} & "
            f"{row['diff_b_minus_a']:+.1f} "
            f"[{row['cluster_ci_low']:+.1f}, {row['cluster_ci_high']:+.1f}] & "
            f"{p_value} & {q_value} \\\\"
        )
    lines.extend(["\\bottomrule", "\\end{tabular}", ""])
    out.write_text("\n".join(lines), encoding="utf-8")


def heat_cell(value: float) -> str:
    gray = 1.0 - 0.35 * (value / 100.0)
    return f"\\cellcolor[gray]{{{gray:.2f}}}{value:.0f}"


def write_model_category_heatmap(df: pd.DataFrame, out: Path) -> None:
    table = (
        df.groupby(["model", "mode", "category"], dropna=False)["semantic_ok"]
        .mean()
        .mul(100)
        .reset_index()
    )
    values = {
        (row["model"], row["mode"], row["category"]): float(row["semantic_ok"])
        for _, row in table.iterrows()
    }
    models = [model for model in MODEL_ORDER if model in set(df["model"])]
    columns: list[tuple[str, str]] = []
    available_modes = set(df["mode"])
    for model in models:
        for mode in MODE_ORDER:
            if mode in available_modes:
                columns.append((model, mode))
    col_spec = "l" + "r" * len(columns)
    header = "Category & " + " & ".join(
        f"{latex_escape(model_label(model))} {MODE_LABELS.get(mode, mode)}"
        for model, mode in columns
    ) + " \\\\"
    lines = ["\\begin{tabular}{" + col_spec + "}", "\\toprule", header, "\\midrule"]
    for category in CATEGORY_ORDER:
        row = [category_label(category).replace("_", "\\_")]
        for model, mode in columns:
            row.append(heat_cell(values.get((model, mode, category), 0.0)))
        lines.append(" & ".join(row) + " \\\\")
    lines.extend(["\\bottomrule", "\\end{tabular}", ""])
    out.write_text("\n".join(lines), encoding="utf-8")


def write_error_examples(raw_rows: list[dict[str, Any]], out: Path) -> None:
    lines = ["# Error examples", ""]
    count = 0
    for raw in raw_rows:
        ev = raw["evaluation"]
        if ev.get("semantic_ok"):
            continue
        lines.extend([
            f"## {raw['model']} / {raw['mode']} / {raw['case']['id']}",
            "",
            f"- Category: `{raw['case']['category']}`",
            f"- Replicate: `{(raw.get('protocol') or {}).get('replicate_index', 0)}`",
            f"- Edit: {raw['case']['utterance']}",
            f"- Expected status: `{raw['case']['expected_status']}`",
            f"- Error: `{ev.get('error')}`",
            f"- Unsafe state change: `{ev.get('unsafe_state_change')}`",
            "",
        ])
        count += 1
        if count >= 12:
            break
    out.write_text("\n".join(lines), encoding="utf-8")


def plot_semantic(df: pd.DataFrame, out: Path) -> None:
    summary = df.groupby(["model", "mode"])["semantic_ok"].mean().mul(100).reset_index()
    pivot = summary.pivot(index="model", columns="mode", values="semantic_ok").fillna(0)
    pivot["order"] = [MODEL_ORDER.index(m) if m in MODEL_ORDER else 99 for m in pivot.index]
    pivot = pivot.sort_values("order").drop(columns=["order"])
    out.parent.mkdir(parents=True, exist_ok=True)
    width, height = max(920, 145 * max(len(pivot), 1) + 240), 420
    margin_l, margin_r, margin_t, margin_b = 190, 30, 42, 95
    plot_w = width - margin_l - margin_r
    plot_h = height - margin_t - margin_b
    modes = [mode for mode in MODE_ORDER if mode in pivot.columns]
    colors = {
        "rewrite": "#718096",
        "rewrite_with_ids": "#33658a",
        "line_patch": "#2f855a",
        "json_patch": "#805ad5",
    }
    group_w = plot_w / max(len(pivot), 1)
    bar_w = min(42, group_w / max(len(modes), 1) * 0.70)
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<style>text{font-family:Arial,Helvetica,sans-serif;font-size:12px;fill:#1a202c}.axis{stroke:#2d3748;stroke-width:1}.grid{stroke:#cbd5e0;stroke-width:1;opacity:.65}.label{font-size:13px}.legend{font-size:12px}</style>',
    ]
    for tick in range(0, 101, 20):
        y = margin_t + plot_h - (tick / 100) * plot_h
        lines.append(f'<line class="grid" x1="{margin_l}" y1="{y:.1f}" x2="{width - margin_r}" y2="{y:.1f}"/>')
        lines.append(f'<text x="{margin_l - 10}" y="{y + 4:.1f}" text-anchor="end">{tick}</text>')
    lines.append(f'<line class="axis" x1="{margin_l}" y1="{margin_t}" x2="{margin_l}" y2="{margin_t + plot_h}"/>')
    lines.append(f'<line class="axis" x1="{margin_l}" y1="{margin_t + plot_h}" x2="{width - margin_r}" y2="{margin_t + plot_h}"/>')
    lines.append(f'<text class="label" x="22" y="{margin_t + plot_h / 2:.1f}" transform="rotate(-90 22 {margin_t + plot_h / 2:.1f})" text-anchor="middle">Semantic success (%)</text>')
    for idx, mode in enumerate(modes):
        x = margin_l + idx * 130
        lines.append(f'<rect x="{x}" y="14" width="14" height="14" fill="{colors.get(mode, "#4a5568")}"/>')
        lines.append(f'<text class="legend" x="{x + 20}" y="26">{MODE_LABELS.get(mode, mode)}</text>')
    for model_idx, (model, row) in enumerate(pivot.iterrows()):
        center = margin_l + group_w * model_idx + group_w / 2
        for mode_idx, mode in enumerate(modes):
            value = float(row.get(mode, 0))
            x = center - (len(modes) * bar_w) / 2 + mode_idx * bar_w
            h = (value / 100) * plot_h
            y = margin_t + plot_h - h
            lines.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w - 5:.1f}" height="{h:.1f}" fill="{colors.get(mode, "#4a5568")}"/>')
            lines.append(f'<text x="{x + (bar_w - 5) / 2:.1f}" y="{max(y - 5, 12):.1f}" text-anchor="middle">{value:.0f}</text>')
        label = model_label(str(model)).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        lines.append(f'<text x="{center:.1f}" y="{height - 68}" text-anchor="end" transform="rotate(-30 {center:.1f} {height - 68})">{label}</text>')
    lines.append("</svg>")
    out.write_text("\n".join(lines), encoding="utf-8")


def reliability_tables(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    expected_replicates = int(df["replicate_index"].max()) + 1
    case_outcomes = (
        df.groupby(["model", "mode", "case_id", "semantic_program_id"], dropna=False)
        .agg(
            replicates_observed=("replicate_index", "nunique"),
            provider_successes=("provider_ok", "sum"),
            semantic_successes=("semantic_ok", "sum"),
            semantic_outcome_variants=("semantic_ok", "nunique"),
            exact_response_variants=("response_sha256", "nunique"),
        )
        .reset_index()
    )
    case_outcomes["replicates_expected"] = expected_replicates
    case_outcomes["complete_replicate_set"] = (
        case_outcomes["replicates_observed"] == expected_replicates
    )
    case_outcomes["all_replicates_provider_ok"] = (
        case_outcomes["complete_replicate_set"]
        & (case_outcomes["provider_successes"] == expected_replicates)
    )
    case_outcomes["all_replicates_semantic_ok"] = (
        case_outcomes["complete_replicate_set"]
        & (case_outcomes["semantic_successes"] == expected_replicates)
    )
    case_outcomes["any_replicate_semantic_ok"] = case_outcomes["semantic_successes"] > 0
    case_outcomes["semantic_outcome_agreement"] = (
        case_outcomes["complete_replicate_set"]
        & (case_outcomes["semantic_outcome_variants"] == 1)
    )
    case_outcomes["exact_response_agreement"] = (
        case_outcomes["all_replicates_provider_ok"]
        & (case_outcomes["exact_response_variants"] == 1)
    )

    summary = (
        case_outcomes.groupby(["model", "mode"], dropna=False)
        .agg(
            n_cases=("case_id", "count"),
            replicates_expected=("replicates_expected", "max"),
            complete_replicate_sets=("complete_replicate_set", pct),
            all_replicates_provider_ok=("all_replicates_provider_ok", pct),
            all_replicates_semantic_ok=("all_replicates_semantic_ok", pct),
            any_replicate_semantic_ok=("any_replicate_semantic_ok", pct),
            semantic_outcome_agreement=("semantic_outcome_agreement", pct),
            exact_response_agreement=("exact_response_agreement", pct),
        )
        .reset_index()
        .sort_values(["model", "mode"])
    )
    return case_outcomes, summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", nargs="+", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, default=Path("results"))
    parser.add_argument("--model-catalog", type=Path)
    args = parser.parse_args()

    pricing = None
    if args.model_catalog:
        catalog = json.loads(args.model_catalog.read_text(encoding="utf-8"))
        pricing = {
            str(row["id"]): {
                "prompt": float(row["pricing"]["prompt"]),
                "completion": float(row["pricing"]["completion"]),
            }
            for row in catalog["models"]
        }
    df, raw_rows = read_runs(args.runs, pricing)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out_dir / "metrics.csv", index=False)

    summary = (
        df.groupby(["model", "mode"], dropna=False)
        .agg(
            n=("case_id", "count"),
            provider_ok=("provider_ok", pct),
            json_valid=("json_valid", pct),
            schema_valid=("schema_valid", pct),
            status_correct=("status_correct", pct),
            order_exact=("order_exact", pct),
            constraints_exact=("constraints_exact", pct),
            state_preserved_when_blocked=("state_preserved_when_blocked", pct),
            semantic_ok=("semantic_ok", pct),
            unsafe_state_change=("unsafe_state_change", pct),
            unintended_drift=("unintended_drift", pct),
            identity_error=("identity_error", pct),
            identity_fidelity=("identity_fidelity", pct),
            identity_observable_n=("identity_observable", "sum"),
            operation_executable=("operation_executable", pct),
            authorized_write_precision=("authorized_write_precision", pct),
            authorized_write_recall=("authorized_write_recall", pct),
            mean_collateral_writes=("collateral_write_count", "mean"),
            mean_latency_s=("latency_s", "mean"),
            total_latency_s=("latency_s", "sum"),
            mean_prompt_tokens=("prompt_tokens", "mean"),
            mean_completion_tokens=("completion_tokens", "mean"),
            semantic_successes=("semantic_ok", "sum"),
            total_estimated_usd=("estimated_cost_usd", lambda values: values.sum(min_count=1)),
        )
        .reset_index()
        .sort_values(["model", "mode"])
    )
    summary["seconds_per_semantic_success"] = summary["total_latency_s"].where(
        summary["semantic_successes"] > 0
    ) / summary["semantic_successes"].where(summary["semantic_successes"] > 0)
    summary["cost_per_semantic_success_usd"] = summary["total_estimated_usd"].where(
        summary["semantic_successes"] > 0
    ) / summary["semantic_successes"].where(summary["semantic_successes"] > 0)
    summary.to_csv(args.out_dir / "summary.csv", index=False)

    by_category = (
        df.groupby(["model", "mode", "category"], dropna=False)
        .agg(
            n=("case_id", "count"),
            semantic_ok=("semantic_ok", pct),
            unsafe_state_change=("unsafe_state_change", pct),
            unintended_drift=("unintended_drift", pct),
            identity_error=("identity_error", pct),
            authorized_write_precision=("authorized_write_precision", pct),
            authorized_write_recall=("authorized_write_recall", pct),
            mean_collateral_writes=("collateral_write_count", "mean"),
        )
        .reset_index()
        .sort_values(["model", "mode", "category"])
    )
    by_category.to_csv(args.out_dir / "by_category.csv", index=False)

    taxonomy = (
        df.groupby(["model", "mode"], dropna=False)
        .agg(n=("case_id", "count"), **{col: (col, pct) for col in TAXONOMY})
        .reset_index()
        .sort_values(["model", "mode"])
    )
    taxonomy.to_csv(args.out_dir / "error_taxonomy.csv", index=False)

    stats = pd.concat(
        [paired_stats(df, metric) for metric in ["semantic_ok", "unsafe_state_change", "unintended_drift"]],
        ignore_index=True,
    )
    stats.to_csv(args.out_dir / "paired_stats.csv", index=False)

    cluster_frames = [
        cluster_paired_stats(df, metric)
        for metric in ["semantic_ok", "unsafe_state_change", "unintended_drift"]
    ]
    cluster_stats = pd.concat(cluster_frames, ignore_index=True) if cluster_frames else pd.DataFrame()
    if not cluster_stats.empty:
        cluster_stats["cluster_sign_flip_q_bh"] = cluster_stats.groupby(
            ["metric", "comparison"], dropna=False
        )["cluster_sign_flip_p"].transform(
            lambda values: _benjamini_hochberg([float(value) for value in values])
        )
    cluster_stats.to_csv(args.out_dir / "paired_cluster_stats.csv", index=False)

    replicate_outcomes, reliability = reliability_tables(df)
    replicate_outcomes.to_csv(args.out_dir / "replicate_outcomes.csv", index=False)
    reliability.to_csv(args.out_dir / "reliability.csv", index=False)

    availability = df.pivot_table(
        index=["model", "case_id", "replicate_index", "semantic_program_id"],
        columns="mode",
        values="provider_ok",
        aggfunc="max",
    ).reset_index()
    mode_columns = [mode for mode in MODE_ORDER if mode in availability.columns]
    availability["all_conditions_available"] = availability[mode_columns].fillna(False).all(axis=1)
    availability.to_csv(args.out_dir / "availability_pairs.csv", index=False)

    write_main_table(df, args.out_dir / "table_main.tex")
    write_category_table(df, args.out_dir / "table_by_category.tex")
    write_taxonomy_table(df, args.out_dir / "table_error_taxonomy.tex")
    if stats.empty and not cluster_stats.empty:
        write_controlled_paired_table(
            cluster_stats, args.out_dir / "table_paired_combined.tex"
        )
    else:
        write_paired_table(stats, args.out_dir / "table_paired_combined.tex")
    write_model_category_heatmap(df, args.out_dir / "table_model_category_heatmap.tex")
    write_error_examples(raw_rows, args.out_dir / "error_examples.md")
    plot_semantic(df, args.out_dir / "figures" / "semantic_success.svg")
    print(f"wrote {len(df)} scored calls to {args.out_dir}")


if __name__ == "__main__":
    main()
