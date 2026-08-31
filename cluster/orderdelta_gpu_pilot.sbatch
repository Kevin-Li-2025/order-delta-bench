#!/usr/bin/env bash
#SBATCH --job-name=orderdelta-v3-pilot
#SBATCH --partition=gpu_5090
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --time=00:45:00
#SBATCH --output=artifacts/slurm-%j.out
#SBATCH --error=artifacts/slurm-%j.err

set -euo pipefail

project_root="$(pwd)"
model_root="/ssd/scxi253/shared-models/Qwen--Qwen2.5-7B-Instruct"
container="/ssd/scxi253/esmfold2/esmfold2_official_vendor_cu128_flashattn_sm120_20260609.sif"

test -f "$project_root/data/orderdelta_v3_identity_controlled.jsonl"
test -f "$model_root/model.safetensors.index.json"
test -f "$container"
mkdir -p "$project_root/artifacts"
mkdir -p "$project_root/artifacts/apptainer-tmp" "$project_root/artifacts/apptainer-cache"
export TMPDIR="$project_root/artifacts/apptainer-tmp"
export APPTAINER_TMPDIR="$project_root/artifacts/apptainer-tmp"
export APPTAINER_CACHEDIR="$project_root/artifacts/apptainer-cache"
source /etc/profile.d/modules.sh
module load apptainer/1.4.5 squashfuse/0.6.1

{
  date -Is
  hostname
  echo "SLURM_JOB_ID=${SLURM_JOB_ID:-unset}"
  echo "CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-unset}"
  nvidia-smi --query-gpu=index,uuid,name,memory.total,driver_version --format=csv,noheader
  apptainer exec --nv --bind /ssd/scxi253:/ssd/scxi253 "$container" \
    python -c 'import torch,transformers; print("torch=" + torch.__version__); print("transformers=" + transformers.__version__); print("cuda=" + str(torch.version.cuda)); print("arches=" + ",".join(torch.cuda.get_arch_list()))'
} | tee "$project_root/artifacts/runtime.txt"

find src cluster -type f -print0 | sort -z | xargs -0 sha256sum > "$project_root/artifacts/source.sha256"
sha256sum data/orderdelta_v3_identity_controlled.jsonl > "$project_root/artifacts/data.sha256"
sha256sum "$container" > "$project_root/artifacts/container.sha256"

APPTAINERENV_PYTHONPATH="$project_root" apptainer exec --nv \
  --bind /ssd/scxi253:/ssd/scxi253 \
  "$container" python -m src.orderdelta.run_local_transformers \
  --dataset "$project_root/data/orderdelta_v3_identity_controlled.jsonl" \
  --out "$project_root/artifacts/qwen25_7b_prompt_only_pilot.jsonl" \
  --model-path "$model_root" \
  --model-id "Qwen/Qwen2.5-7B-Instruct-local" \
  --modes rewrite_with_ids line_patch json_patch \
  --limit-per-category 1 \
  --seed 20260831 \
  --max-new-tokens 700

date -Is > "$project_root/artifacts/COMPLETE"
