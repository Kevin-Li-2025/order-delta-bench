# Provider promotion protocol

All provider requests use the identity-bearing v3 dataset, temperature `0`,
strict JSON Schema response formats, counterbalanced interface order, and raw
request/response provenance. Costs below are estimates from the live catalog
price fields and returned token usage; they are not billing invoices.

## Output-budget pilots

| Pilot | Calls | Provider errors | Length finishes | Estimated cost |
| --- | ---: | ---: | ---: | ---: |
| 7 models, 900 tokens | 252 | 0 | 13 | $0.205638 |
| same 7 models, 2,400 tokens | 252 | 0 | 4 | $0.214724 |
| DeepSeek-V4-Flash only, 6,000 tokens | 36 | 0 | 4 | $0.018542 |
| Hermes-4-405B replacement, 2,400 tokens | 36 | 0 | 0 | $0.065340 |

The four remaining 2,400-token truncations all belonged to
`deepseek-ai/DeepSeek-V4-Flash`. The same model still exhausted 6,000 tokens on
four of 36 requests without producing a JSON object. It was therefore marked
incompatible with the bounded structured-output protocol and was not promoted.
This is a protocol-compatibility decision, not a general model-quality claim.

`NousResearch/Hermes-4-405B` was selected from the live catalog as the
replacement. Its targeted pilot had 36/36 provider-successful, JSON-valid,
schema-valid, non-truncated responses.

## Promoted experiment

- Experiment ID: `v3-controlled-20260831-r3`
- Cases: 360
- Interfaces: `rewrite_with_ids`, `line_patch`, `json_patch`
- Repeated provider requests per model/interface/case: 3
- Output budget: 2,400 tokens
- Total expected calls: 22,680
- Raw storage: one append-only, resumable JSONL file per model
- Model selection gate: present in the live catalog and advertises
  `structured_outputs`

Promoted models:

1. `Qwen/Qwen3-235B-A22B-Instruct-2507`
2. `Qwen/Qwen3-32B`
3. `openai/gpt-oss-120b`
4. `NousResearch/Hermes-4-70B`
5. `NousResearch/Hermes-4-405B`
6. `nvidia/Cosmos3-Super-Reasoner`
7. `zai-org/GLM-5.1`

The three replicates are independent API requests at deterministic decoding;
they measure serving/output variability but are not independent task designs.
Inference must cluster at the hand-written `semantic_program_id` level.

## Reporting rules

The primary controlled contrast is `line_patch - rewrite_with_ids` for
unconditional `semantic_ok`, reported separately for every model. Confidence
intervals resample the 96 hand-written `semantic_program_id` clusters rather
than treating 360 lexicalized cases or three repeated API requests as
independent designs. A cluster sign-flip test and Benjamini-Hochberg adjustment
across the seven model-specific primary tests accompany the interval.

Secondary outcomes are unsafe state change, unintended drift, authorized-write
precision/recall, output tokens, latency, and catalog-price-estimated cost per
correct mutation. The repeated calls are summarized with all-three semantic
success and exact-output agreement; they are not used to triple the effective
sample size. Provider failures remain unconditional failures, with paired
availability exported separately instead of silently dropping one condition.

`json_patch` is an exploratory standard-interface contrast. Any result applies
to the exact schema, prompt contract, models, provider deployments, and output
budget recorded here; it is not a universal claim about RFC 6902. Costs are
estimates from the catalog snapshot and returned token counts, not invoices.
