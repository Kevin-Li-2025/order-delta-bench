# OrderDeltaBench

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.20236620.svg)](https://doi.org/10.5281/zenodo.20236620)
[![CI](https://github.com/yinli-systems/order-delta-bench/actions/workflows/ci.yml/badge.svg)](https://github.com/yinli-systems/order-delta-bench/actions/workflows/ci.yml)

## Positioning

OrderDeltaBench is kept as a stateful agent-interface benchmark. Its role is to
isolate one reliability question: whether an ordering agent should rewrite the
whole cart state or emit stable-line patch operations.

It is not a general ordering app, RAG stack, or scientific-agent runtime.
Broader trace/reward infrastructure belongs in
[SciTrace-RL](https://github.com/yinli-systems/scitrace-rl), and retrieval or
citation tooling belongs in
[SignalRAG](https://github.com/yinli-systems/signal-rag). New work here should
stay focused on deterministic state semantics and benchmark evidence.

OrderDeltaBench is a deterministic benchmark for measuring stateful semantic
reliability in LLM-powered ordering agents.

It tests a simple interface question:

> Should an ordering agent rewrite the entire cart after each user edit, or emit
> a minimal operation over stable cart line IDs?

Across 360 cart-edit cases, the benchmark evaluates whether models preserve
existing cart state while correctly applying edits such as quantity changes,
scoped modifier updates, item replacement, unavailable requests, newly stated
constraints, and stale references. Every case includes an edit history field,
but the current cart remains the authoritative state.

The v2 expanded run contains 5,040 scored Nebius calls across 7 open-weight
models and 2 strict structured-output interfaces: `rewrite` and `line_patch`.

## Main Finding

Line-patch interfaces reduce locality and identity failures, but they are not
universally better than rewriting. Aggregated across all seven models, line
patch raises exact semantic success from 58.1% to 62.0%, reduces unintended cart
drift from 6.3% to 3.6%, and reduces wrong-line identity errors from 2.5% to
0.8%.

The effect is model-dependent. Qwen3-32B improves from 64.7% to 80.8%
semantic success, and Llama-3.1-8B improves from 25.3% to 48.1%. Stronger
models such as Qwen3-235B-A22B, Llama-3.3-70B, and Nemotron-Ultra-253B are
close, with rewrite slightly ahead on exact semantic success. Safety and catalog
decisions remain hard under both interfaces.

## Headline Results

| Model | Rewrite Semantic | Line Patch Semantic | Delta | Rewrite Drift | Line Patch Drift | Rewrite Unsafe | Line Patch Unsafe |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Qwen3-235B-A22B | 86.1 | 83.9 | -2.2 | 0.0 | 0.8 | 1.9 | 0.6 |
| Qwen3-32B | 64.7 | 80.8 | +16.1 | 5.8 | 4.4 | 21.9 | 7.2 |
| Qwen3-30B-A3B | 74.2 | 70.0 | -4.2 | 3.6 | 5.3 | 6.9 | 7.2 |
| Llama-3.3-70B | 76.7 | 72.8 | -3.9 | 4.4 | 2.8 | 3.1 | 2.8 |
| Llama-3.1-8B | 25.3 | 48.1 | +22.8 | 29.4 | 11.4 | 9.7 | 6.9 |
| Gemma-2-2B | 0.0 | 0.0 | +0.0 | 0.8 | 0.0 | 1.9 | 11.1 |
| Nemotron-Ultra-253B | 79.7 | 78.3 | -1.4 | 0.0 | 0.3 | 0.0 | 0.0 |

Values are percentages. `Delta` is line patch minus rewrite. Full paired
bootstrap and McNemar statistics are in `results/expanded/paired_stats.csv`.

## Why This Version Is Stronger

The v2 expansion follows patterns used by stronger agent benchmarks:

- stateful evaluation rather than one-shot text classification, following the
  motivation of ToolSandbox and tau-bench;
- deterministic state checking rather than subjective judging, similar in
  spirit to execution or database-state evaluation;
- broader model coverage, including model families where the interface choice
  changes the failure profile;
- raw logs, parsed outputs, verifier scores, paired statistics, category
  breakdowns, and error taxonomy.

OrderDeltaBench is still deliberately narrower than general tool-use
benchmarks. Its value is isolating one interface-design variable: full resource
rewrite versus stable-ID patch operations.

## Example Case

The current cart contains two similar burgers and a side:

```json
{
  "current_order": {
    "items": [
      {
        "line_id": "L1",
        "sku": "classic_burger",
        "quantity": 1,
        "size": "single",
        "add": [],
        "remove": ["onion"],
        "special_instructions": ""
      },
      {
        "line_id": "L2",
        "sku": "classic_burger",
        "quantity": 1,
        "size": "double",
        "add": [],
        "remove": [],
        "special_instructions": ""
      },
      {
        "line_id": "L3",
        "sku": "fries",
        "quantity": 1,
        "size": "regular",
        "add": [],
        "remove": [],
        "special_instructions": ""
      }
    ],
    "constraints": {"allergens": [], "dietary": []}
  },
  "edit_history": [
    "One burger was customized without onion.",
    "A second burger was later upgraded to double."
  ],
  "user_edit": "Remove the double burger."
}
```

The rewrite interface must return the complete final order without accidentally
dropping or changing `L1` and `L3`. The line-patch interface can express the
same edit locally:

```json
{
  "status": "accepted",
  "operations": [
    {
      "op": "remove_line",
      "line_id": "L2",
      "item": null,
      "quantity": null,
      "size": null,
      "add": [],
      "remove": [],
      "remove_add": [],
      "remove_remove": [],
      "constraints": null,
      "reason": "Remove the double classic burger line."
    }
  ],
  "clarification_question": null,
  "reasons": []
}
```

## Metrics

- `provider_ok`: provider call completed.
- `json_valid`: response contained a JSON object after limited extraction.
- `schema_valid`: parsed object matched the interface schema.
- `status_correct`: model chose the oracle status.
- `order_exact`: final item multiset exactly matched the oracle final cart.
- `constraints_exact`: allergen and dietary constraints exactly matched.
- `semantic_ok`: schema-valid, executable, correct status, exact final order,
  exact constraints, and fail-closed state preservation for non-accepted edits.
- `unsafe_state_change`: model accepted or changed state when the oracle
  required clarification/safety rejection, or accepted a final cart that
  conflicts with stated constraints.
- `unintended_drift`: model changed cart lines marked as unchanged.
- `identity_error`: wrong-line edit in a case with a target line.
- `operation_executable`: patch operations could be applied to the current
  cart without missing lines or malformed operation semantics.

Scoring details are documented in `verifier_scoring.md`.

## Dataset

The v2 benchmark contains 12 categories with 30 cases each:

- `add_item`
- `remove_scoped_duplicate`
- `quantity_increase`
- `quantity_decrease`
- `modifier_add_scoped`
- `modifier_reversal`
- `size_change_scoped`
- `replace_item`
- `constraint_add_safe`
- `constraint_new_conflict`
- `unavailable_add`
- `stale_reference`

Each category is generated from 8 hand-written semantic templates plus lexical
prefix/suffix variation. All 360 cases include `edit_history`, `current_order`,
oracle `expected_order`, `expected_status`, target line IDs, unchanged line IDs,
and rationale metadata. No model is used to create oracle labels.

## Artifact Files

- `data/orderdelta_v2_expanded.jsonl`: expanded deterministic benchmark cases
- `results/raw/orderdelta_v2_expanded.jsonl`: raw model outputs and verifier scores
- `results/expanded/summary.csv`: headline metrics
- `results/expanded/by_category.csv`: model/category breakdowns
- `results/expanded/paired_stats.csv`: paired bootstrap and McNemar statistics
- `results/expanded/error_taxonomy.csv`: failure taxonomy
- `results/expanded/figures/semantic_success.svg`: generated result figure
- `src/orderdelta/`: generator, prompts, schemas, verifier, runner, analysis
- `paper/main.tex`: journal-style manuscript draft
- `paper/main.pdf`: compiled PDF
- `paper/references.bib`: bibliography
- `highlights.txt`: JSS-style highlights file
- `journal_target.md`: JSS fit and author-guide checklist
- `CITATION.cff`: citation metadata for the archived artifact

The original v1 120-case run is preserved under `data/orderdelta_v1.jsonl` and
`results/main/`.

## Evidence Boundaries

- The checked-in v2 tables summarize 5,040 recorded provider calls. The
  CPU-safe CI does not rerun those paid model requests.
- Dataset generation, schema/evaluator contract tests, and source compilation
  are reproducible offline in CI.
- Lexical variants are generated from eight hand-written templates per
  category. They broaden phrasing, but they are not 360 independent semantic
  task designs.
- Deterministic scoring establishes agreement with the benchmark oracle; it
  does not establish restaurant deployment safety or performance on menus and
  policies outside this fixture.

## Offline Verification

The following checks require no API key and are the quickest way to review the
benchmark machinery:

```bash
python3 -m compileall -q src tests
python3 -m unittest discover -s tests -v

python3 -m src.orderdelta.generate_dataset \
  --out /tmp/orderdelta_v2_expanded.jsonl \
  --cases-per-category 30
cmp data/orderdelta_v2_expanded.jsonl /tmp/orderdelta_v2_expanded.jsonl
```

The evaluator tests explicitly enforce the public quantity contract: JSON
integers from 1 through 20 are accepted, while booleans and out-of-range values
are rejected. This keeps the hand-written offline validator aligned with the
structured-output schema used for provider calls. The source tree also compiles
on Python 3.11; LaTeX escaping is kept outside f-string expressions so the
analysis CLI does not silently require Python 3.12.

## Improvement Priorities

1. Add independent semantic templates and multi-turn mutations instead of
   relying primarily on lexical expansion.
2. Version provider/model metadata and request parameters in a compact run
   manifest so future reruns can be compared without inspecting every raw row.
3. Expand contract-conformance tests across modifier availability, duplicate
   line IDs, and operation-specific required fields.
4. Rerun selected model families only when the exact endpoint revision and raw
   outputs can be published alongside the aggregate tables.

## Citation

The archived v0.1.0 artifact is available on Zenodo:
[https://doi.org/10.5281/zenodo.20236620](https://doi.org/10.5281/zenodo.20236620).

```bibtex
@misc{li2026orderdeltabench,
  author = {Li, Yin},
  title = {{OrderDeltaBench}: Initial Research Artifact},
  year = {2026},
  publisher = {Zenodo},
  version = {v0.1.0},
  doi = {10.5281/zenodo.20236620},
  url = {https://doi.org/10.5281/zenodo.20236620}
}
```

## Reproduce

```bash
python3 -m src.orderdelta.generate_dataset \
  --out data/orderdelta_v2_expanded.jsonl \
  --cases-per-category 30

read -rs NEBIUS_API_KEY
export NEBIUS_API_KEY

python3 -m src.orderdelta.run_nebius \
  --dataset data/orderdelta_v2_expanded.jsonl \
  --out results/raw/orderdelta_v2_expanded.jsonl \
  --models \
    Qwen/Qwen3-235B-A22B-Instruct-2507 \
    Qwen/Qwen3-32B \
    Qwen/Qwen3-30B-A3B-Instruct-2507 \
    meta-llama/Llama-3.3-70B-Instruct \
    meta-llama/Meta-Llama-3.1-8B-Instruct \
    google/gemma-2-2b-it \
    nvidia/Llama-3_1-Nemotron-Ultra-253B-v1 \
  --modes rewrite line_patch \
  --concurrency 12 \
  --max-retries 1 \
  --request-timeout 75 \
  --progress-every 50

python3 -m src.orderdelta.analyze \
  --runs results/raw/orderdelta_v2_expanded.jsonl \
  --out-dir results/expanded

TECTONIC_CACHE_DIR="$PWD/.tectonic-cache" tectonic \
  --outdir paper paper/main.tex
```

API keys are read only from the environment and are not written to the
workspace.
