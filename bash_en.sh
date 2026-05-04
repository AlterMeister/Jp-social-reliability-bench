#!/usr/bin/env bash
set -euo pipefail

########################################
# Config
########################################

CONDA_ENV="NewJulian"

# 固定输入 benchmark 文件路径
BENCHMARK_PATH="/home/liujiajun/JP-reliability/configs_v1/en_v1.jsonl"

# 固定输出目录
OUTPUT_DIR=".out"

# runner module
RUNNER_MODULE="scripts.runner_open_source"

# generation config
MAX_NEW_TOKENS=256
TEMPERATURE=0.6
TOP_P=0.9

# 日志目录
LOG_DIR="logs/open_source_runner"

########################################
# Init conda
########################################

if ! command -v conda >/dev/null 2>&1; then
  echo "[ERROR] conda command not found. Please make sure conda is installed."
  exit 1
fi

# 让 bash 脚本里可以使用 conda activate
CONDA_BASE="$(conda info --base)"
# shellcheck disable=SC1091
source "${CONDA_BASE}/etc/profile.d/conda.sh"

set +u
conda activate "${CONDA_ENV}"
set -u

mkdir -p "${OUTPUT_DIR}"
mkdir -p "${LOG_DIR}"

echo "[INFO] Conda env: ${CONDA_ENV}"
echo "[INFO] Benchmark path: ${BENCHMARK_PATH}"
echo "[INFO] Output dir: ${OUTPUT_DIR}"
echo "[INFO] Log dir: ${LOG_DIR}"
echo

########################################
# Model list
# 格式:
#   "GPU_ID|MODEL_PATH"
########################################

MODELS=(
  "1|/data/model/Qwen3-32B"
  "1|/data/model/Llama-3-ELYZA-JP-8B"
  "1|/data/model/Mistral-7B-Instruct-v0.1"
  "1|/data/model/Llama-3.1-8B-Instruct"
  "1|/data/model/llm-jp-4-8b-thinking"
  "1|/data/model/llm-jp-4-8b-instruct"
  "1|/data/model/Llama-3.3-70B-Instruct"
  "1|/data/model/Qwen2.5-7B-Instruct"
  "1|/data/model/ELYZA-Shortcut-1.0-Qwen-7B"
  "1|/data/model/llm-jp-4-32b-a3b-thinking"
)

########################################
# Run
########################################

run_one_model() {
  local gpu_id="$1"
  local model_name="$2"

  local model_base
  model_base="$(basename "${model_name}")"

  local timestamp
  timestamp="$(date +"%Y%m%d_%H%M%S")"

  local log_file="${LOG_DIR}/${model_base}_${timestamp}.log"

  echo "========================================"
  echo "[INFO] Running model: ${model_name}"
  echo "[INFO] GPU: ${gpu_id}"
  echo "[INFO] Log: ${log_file}"
  echo "========================================"

  CUDA_VISIBLE_DEVICES="${gpu_id}" python -m "${RUNNER_MODULE}" \
    --model_name "${model_name}" \
    --benchmark_path "${BENCHMARK_PATH}" \
    --output_dir "${OUTPUT_DIR}" \
    --max_new_tokens "${MAX_NEW_TOKENS}" \
    --temperature "${TEMPERATURE}" \
    --top_p "${TOP_P}" \
    --do_sample \
    2>&1 | tee "${log_file}"

  echo "[INFO] Finished model: ${model_name}"
  echo
}

FAILED_MODELS=()

for entry in "${MODELS[@]}"; do
  IFS="|" read -r gpu_id model_name <<< "${entry}"

  if run_one_model "${gpu_id}" "${model_name}"; then
    echo "[SUCCESS] ${model_name}"
  else
    echo "[FAILED] ${model_name}"
    FAILED_MODELS+=("${model_name}")
  fi

  echo
done

########################################
# Summary
########################################

echo "========================================"
echo "[SUMMARY]"
echo "========================================"

if [ "${#FAILED_MODELS[@]}" -eq 0 ]; then
  echo "All models finished successfully."
else
  echo "Some models failed:"
  for model in "${FAILED_MODELS[@]}"; do
    echo " - ${model}"
  done
  exit 1
fi