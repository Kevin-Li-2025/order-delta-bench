#!/usr/bin/env bash
set -uo pipefail

: "${NEBIUS_API_KEY:?NEBIUS_API_KEY must be set in the environment}"

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
PYTHON_BIN=${ORDERDELTA_PYTHON:-python3}
EXPERIMENT_ID=${ORDERDELTA_EXPERIMENT_ID:-v3-controlled-20260831-r3}
DATASET=${ORDERDELTA_DATASET:-data/orderdelta_v3_identity_controlled.jsonl}
MODEL_CATALOG=${ORDERDELTA_MODEL_CATALOG:-results/provider_v3/model_catalog_formal_20260831.json}
OUT_ROOT=${ORDERDELTA_OUT_ROOT:-results/provider_v3/formal}

cd "$REPO_ROOT"
mkdir -p "$OUT_ROOT/raw" "$OUT_ROOT/logs"

run_model() {
  local model=$1
  local slug=$2
  local concurrency=$3
  "$PYTHON_BIN" -m src.orderdelta.run_nebius \
    --dataset "$DATASET" \
    --out "$OUT_ROOT/raw/${slug}.jsonl" \
    --experiment-id "$EXPERIMENT_ID" \
    --replicates 3 \
    --model-catalog "$MODEL_CATALOG" \
    --models "$model" \
    --modes rewrite_with_ids line_patch json_patch \
    --seed 20260831 \
    --concurrency "$concurrency" \
    --max-retries 2 \
    --max-tokens 2400 \
    --request-timeout 180 \
    --progress-every 50 \
    >"$OUT_ROOT/logs/${slug}.log" 2>&1
}

models=(
  "Qwen/Qwen3-235B-A22B-Instruct-2507|qwen3_235b|8"
  "Qwen/Qwen3-32B|qwen3_32b|8"
  "openai/gpt-oss-120b|gpt_oss_120b|8"
  "NousResearch/Hermes-4-70B|hermes4_70b|4"
  "NousResearch/Hermes-4-405B|hermes4_405b|4"
  "nvidia/Cosmos3-Super-Reasoner|cosmos3_super_reasoner|8"
  "zai-org/GLM-5.1|glm_5_1|8"
)

pids=()
slugs=()
for specification in "${models[@]}"; do
  IFS='|' read -r model slug concurrency <<<"$specification"
  run_model "$model" "$slug" "$concurrency" &
  pids+=("$!")
  slugs+=("$slug")
  echo "started $slug pid=${pids[${#pids[@]}-1]}"
done

status=0
for index in "${!pids[@]}"; do
  if wait "${pids[$index]}"; then
    echo "completed ${slugs[$index]}"
  else
    echo "failed ${slugs[$index]}" >&2
    status=1
  fi
done
exit "$status"
