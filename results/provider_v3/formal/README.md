# Controlled v3 provider experiment

This directory contains the promoted identity-aware experiment. The primary
question is whether a typed stable-ID patch improves state mutation reliability
over a full-state rewrite when both interfaces receive the same identity-bearing
input. `json_patch` is an exploratory third condition.

## Integrity receipt

- Experiment: `v3-controlled-20260831-r3`
- Design: 360 cases × 3 interfaces × 3 independent API requests × 7 models
- Expected and recorded keys: 22,680 / 22,680
- Provider-successful calls: 22,461 / 22,680
- Duplicate case keys / unexpected keys / protocol mismatches: 0 / 0 / 0
- Unique provider request IDs: 22,461; duplicates: 0
- Evaluator replay: 22,680 / 22,680 identical; 0 mismatches
- Request/scoring source commit: `faa42571498649cc358f0f36c5289b0a7c6650eb`
- Recorded source digest: `c168705855a7222eb7692a932faf3ab57c758ab09dc5de56c3ddfaad4db68c81`
- Dataset digest: `6d866c7eb41aac68c142a46aa8d198aeacbae45de2eaf603cadd7165ec89a99c`
- Catalog digest: `229b88453f3f81fd863980fbd4ce1bf6d39c1b157c9600069b03e2e552ca40f0`
- Fixed generation configuration: temperature 0, maximum 2,400 output tokens
- Catalog-price estimate from returned usage: `$24.329215`; this is not an invoice

The final 219 GLM-5.1 calls exhausted the supplied provider budget after all
configured retries and returned HTTP 402. The failures are balanced exactly
across the three interfaces (73 each); the other six models completed
19,440/19,440 calls. Primary rates below are unconditional, so provider failures
remain failures. The provider-success-only sensitivity analysis is preserved
separately.

## Primary controlled result

The rate columns are unconditional case-request means. The effect and interval
give the typed-patch-minus-ID-rewrite difference after averaging within each of
the 96 hand-written `semantic_program_id` clusters. `p` is a cluster sign-flip
test; `q` applies Benjamini-Hochberg adjustment across the seven model-specific
primary comparisons.

| Model | Rewrite + IDs | Typed patch | Cluster delta | 95% cluster CI | p | BH q |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Qwen3-235B-A22B | 80.2% | 85.9% | +5.4 | [-0.4, +11.8] | .0891 | .1247 |
| Qwen3-32B | 65.5% | 85.3% | +20.3 | [+12.4, +28.4] | .00005 | .00035 |
| gpt-oss-120b | 91.3% | 91.9% | +0.1 | [-4.0, +4.4] | .9688 | .9688 |
| Hermes-4-70B | 74.1% | 68.6% | -5.4 | [-13.5, +2.6] | .1984 | .2315 |
| Hermes-4-405B | 82.6% | 88.6% | +6.2 | [-0.5, +13.0] | .0696 | .1219 |
| Cosmos3-Super-Reasoner | 69.3% | 81.9% | +12.7 | [+6.7, +19.4] | .00010 | .00035 |
| GLM-5.1 | 79.4% | 85.7% | +6.3 | [+0.7, +12.6] | .0416 | .0971 |

Only Qwen3-32B and Cosmos3-Super-Reasoner remain significant after the declared
cluster-level multiple-comparison adjustment. GLM-5.1 does not: after filtering
to provider-successful calls, its effect is +5.9 points, CI [+0.3, +12.4],
cluster `p=.0564`, BH `q=.1219`. The experiment therefore supports a
model-dependent interface effect, not a universal patch advantage.

## Repeated-request reliability

`All 3` is the percentage of the 360 cases that succeeded in all three API
requests. `Exact` requires byte-identical returned text across all three calls.
Exact-text variability can include semantically irrelevant formatting or
reason strings; it is reported as serving/output variability, not as a quality
metric by itself.

| Model | Rewrite all 3 | Patch all 3 | Rewrite exact | Patch exact |
| --- | ---: | ---: | ---: | ---: |
| Qwen3-235B-A22B | 78.3% | 82.5% | 47.8% | 6.4% |
| Qwen3-32B | 64.2% | 84.7% | 48.9% | 74.2% |
| gpt-oss-120b | 88.1% | 89.7% | 35.6% | 2.2% |
| Hermes-4-70B | 73.3% | 65.3% | 43.3% | 32.2% |
| Hermes-4-405B | 81.9% | 87.5% | 75.6% | 55.0% |
| Cosmos3-Super-Reasoner | 68.9% | 81.4% | 49.4% | 62.8% |
| GLM-5.1 | 65.6% | 72.2% | 21.4% | 3.9% |

GLM reliability includes the balanced provider-budget failures and is not a
model-only estimate. Across the other six models, semantic outcome agreement is
93.1%–99.4%, despite much lower exact-text agreement for several deployments.

## Exploratory JSON Patch condition

JSON Patch achieved 0 exact semantic successes for every model under this exact
contract. All 7,353 schema-valid JSON Patch responses failed the required first
`test /version` operation; the remaining responses were truncated, malformed,
empty, or provider failures. This is evidence about the recorded generic schema,
prompt rules, model deployments, and output budget. It is not evidence that RFC
6902 is universally unsuitable for model-generated state updates.

## Efficiency

Typed patches use fewer completion tokens than ID rewrites for all seven models.
Because their prompts are larger, cost per correct mutation is not uniformly
lower. It improves for Qwen3-32B, gpt-oss-120b, Cosmos3-Super-Reasoner, and
GLM-5.1, while Qwen3-235B and both Hermes deployments are slightly more
expensive per correct result. Exact values are in `analysis/summary.csv`.

## Artifacts and reproduction

- `raw/*.jsonl.gz`: deterministic gzip archives of the append-only raw records
- `audit.json`: structural, protocol, request-ID, finish-reason, usage, and cost receipt
- `evaluation_replay.json`: independent evaluator replay receipt
- `executed_source_manifest.json` and `source_verification.json`: executed-source provenance
- `analysis/`: unconditional primary analysis
- `analysis_provider_ok_sensitivity/`: provider-success-only sensitivity analysis

```bash
python -m src.orderdelta_tools.audit_provider_run \
  --runs results/provider_v3/formal/raw/*.jsonl.gz \
  --dataset data/orderdelta_v3_identity_controlled.jsonl \
  --model-catalog results/provider_v3/model_catalog_formal_20260831.json \
  --experiment-id v3-controlled-20260831-r3 \
  --replicates 3 \
  --out /tmp/orderdelta-audit.json \
  --require-complete

python -m src.orderdelta_tools.replay_provider_evaluations \
  --runs results/provider_v3/formal/raw/*.jsonl.gz \
  --out /tmp/orderdelta-replay.json

python -m src.orderdelta.analyze \
  --runs results/provider_v3/formal/raw/*.jsonl.gz \
  --model-catalog results/provider_v3/model_catalog_formal_20260831.json \
  --out-dir /tmp/orderdelta-analysis

python -m src.orderdelta.analyze \
  --runs results/provider_v3/formal/raw/*.jsonl.gz \
  --model-catalog results/provider_v3/model_catalog_formal_20260831.json \
  --provider-ok-only \
  --out-dir /tmp/orderdelta-analysis-provider-ok
```

The shell expands the raw-file glob; paths must not be quoted as one literal
argument. See `../PILOT_PROTOCOL.md` for promotion and reporting rules.
