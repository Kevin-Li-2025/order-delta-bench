# RTX 5090 engineering pilot

This directory preserves the complete local copy of a small, prompt-only GPU
pilot. It is an engineering receipt for the runner and verifier, not a model
ranking or a publication result.

## Scope

- Model: `Qwen/Qwen2.5-7B-Instruct`, loaded from a pre-existing read-only
  cluster copy.
- Hardware: one NVIDIA GeForce RTX 5090 (32,607 MiB), Slurm job `1503264`.
- Runtime: PyTorch `2.11.0+cu128`, CUDA `12.8`, Transformers `4.57.6`.
- Sample: one deterministic case from each of 12 categories, three controlled
  interfaces, one greedy trial (`36` generations total).
- Decoding: prompt-only JSON instructions; no provider-side constrained
  decoding.

The three interfaces receive the same state information. The pilot is too
small and lacks repeated trials, multiple models, and constrained decoding, so
the percentages below must not be used as headline performance claims.

| Interface | n | Schema valid | Semantic success | Operation executable |
| --- | ---: | ---: | ---: | ---: |
| `rewrite_with_ids` | 12 | 41.7% | 8.3% | 100.0% |
| `line_patch` | 12 | 91.7% | 58.3% | 91.7% |
| `json_patch` | 12 | 100.0% | 8.3% | 8.3% |

`json_patch` was usually syntactically valid but not executable because the
model omitted the mandatory version `test`. This is useful protocol-debugging
evidence, not evidence that JSON Patch is intrinsically worse.

## Receipts

- `remote_artifacts/qwen25_7b_prompt_only_pilot.jsonl`: raw remote output.
- `qwen25_7b_prompt_only_pilot.rescored.jsonl`: immutable re-score with the
  final local verifier.
- `analysis/`: aggregate tables, cluster-aware paired statistics, error
  examples, and a figure.
- `remote_artifacts/runtime.txt`: allocation and runtime identity.
- `remote_artifacts/{data,container,source}.sha256`: remote hash receipts.
- `executed_source.tgz`: exact files enumerated by `source.sha256`, including
  the source copied back from the run.
- `remote_artifacts/slurm_logs.tgz`: exact stdout/stderr from both Slurm jobs;
  job `1503183` is the retained negative control showing the original PyTorch
  runtime lacked RTX 5090 `sm_120` kernels.
- `CLEANUP.md`: remote deletion and post-deletion verification receipt.

The final runner now fails before model loading when the installed PyTorch does
not contain the GPU's compute capability.
