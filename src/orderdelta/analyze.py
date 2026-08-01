from __future__ import annotations

import argparse
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
    "operation_executable",
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
    "Qwen/Qwen3.5-397B-A17B-fast",
    "Qwen/Qwen3-32B",
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
    "rewrite": "rewrite",
    "line_patch": "line patch",
}


def model_label(model: str) -> str:
    return MODEL_LABELS.get(model, model.split("/")[-1])


def category_label(category: str) -> str:
    return CATEGORY_LABELS.get(category, category)


def latex_escape(value: str) -> str:
    """Escape identifiers without backslashes inside f-string expressions."""
    return value.replace("_", "\\_")


def pct(x: pd.Series) -> float:
    return float(x.mean() * 100)


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


def read_runs(paths: list[Path]) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    rows_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    raw_rows: list[dict[str, Any]] = []
    for path in paths:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                raw = json.loads(line)
                ev = raw["evaluation"]
                record = {
                    "model": raw["model"],
                    "mode": raw["mode"],
                    "case_id": raw["case"]["id"],
                    "category": raw["case"]["category"],
                    "provider_ok": raw["result"].get("ok", False),
                    "latency_s": raw["result"].get("latency_s"),
                    "prompt_tokens": (raw["result"].get("usage") or {}).get("prompt_tokens"),
                    "completion_tokens": (raw["result"].get("usage") or {}).get("completion_tokens"),
                    **{metric: bool(ev.get(metric, False)) for metric in METRICS},
                    **classify_errors(ev),
                    "error": ev.get("error") or raw["result"].get("provider_error"),
                }
                rows_by_key[(record["model"], record["mode"], record["case_id"])] = record
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
    summary["mode_order"] = summary["mode"].map({"rewrite": 0, "line_patch": 1})
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
    table["mode_order"] = table["mode"].map({"rewrite": 0, "line_patch": 1})
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
    labels = {
        "unsafe_state_change": "Unsafe",
        "unintended_drift": "Drift",
        "identity_error": "Identity",
        "status_error": "Status",
        "order_error": "Order",
        "constraint_error": "Constraint",
        "operation_error": "Operation",
    }
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
        pivot = group.pivot(index="case_id", columns="mode", values=metric)
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
    return pd.DataFrame(rows).sort_values(["metric", "model"])


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
    for model in models:
        columns.append((model, "rewrite"))
        columns.append((model, "line_patch"))
    col_spec = "l" + "r" * len(columns)
    header = "Category & " + " & ".join(
        f"{latex_escape(model_label(model))} {('R' if mode == 'rewrite' else 'P')}"
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
    modes = [mode for mode in ["rewrite", "line_patch"] if mode in pivot.columns]
    colors = {"rewrite": "#33658a", "line_patch": "#2f855a"}
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", nargs="+", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, default=Path("results"))
    args = parser.parse_args()

    df, raw_rows = read_runs(args.runs)
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
            operation_executable=("operation_executable", pct),
            mean_latency_s=("latency_s", "mean"),
            mean_prompt_tokens=("prompt_tokens", "mean"),
            mean_completion_tokens=("completion_tokens", "mean"),
        )
        .reset_index()
        .sort_values(["model", "mode"])
    )
    summary.to_csv(args.out_dir / "summary.csv", index=False)

    by_category = (
        df.groupby(["model", "mode", "category"], dropna=False)
        .agg(
            n=("case_id", "count"),
            semantic_ok=("semantic_ok", pct),
            unsafe_state_change=("unsafe_state_change", pct),
            unintended_drift=("unintended_drift", pct),
            identity_error=("identity_error", pct),
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

    write_main_table(df, args.out_dir / "table_main.tex")
    write_category_table(df, args.out_dir / "table_by_category.tex")
    write_taxonomy_table(df, args.out_dir / "table_error_taxonomy.tex")
    write_paired_table(stats, args.out_dir / "table_paired_combined.tex")
    write_model_category_heatmap(df, args.out_dir / "table_model_category_heatmap.tex")
    write_error_examples(raw_rows, args.out_dir / "error_examples.md")
    plot_semantic(df, args.out_dir / "figures" / "semantic_success.svg")
    print(f"wrote {len(df)} scored calls to {args.out_dir}")


if __name__ == "__main__":
    main()
