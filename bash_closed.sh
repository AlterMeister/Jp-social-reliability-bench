#!/usr/bin/env bash
set -eo pipefail

########################################
# Config
########################################

CONDA_ENV="NewJulian"

RUNNER_MODULE="scripts.runner_closed_source"

OUTPUT_DIR=".out_closed_source_v2"
LOG_DIR="logs/closed_source_runner_v2"

TEMPERATURE="0.01"
MAX_NEW_TOKENS="256"

MAX_RETRIES="5"
RETRY_SLEEP="5"

# 三个固定输入文件路径
BENCHMARK_FILES=(
  "/home/liujiajun/JP-reliability/configs_v1/ja_v2.jsonl"
  "/home/liujiajun/JP-reliability/configs_v1/en_v2.jsonl"
  "/home/liujiajun/JP-reliability/configs_v1/zh_v2.jsonl"
)

# 要跑的 API 模型
# 格式: provider|model_name
MODELS=(
  "claude|claude-haiku-4-5-20251001"
  "gemini|gemini-3-flash-preview"
  "qwen|qwq-32b"
  "gpt|gpt-5.1"
  "deepseek|deepseek-chat"
)

########################################
# Init conda
########################################

if ! command -v conda >/dev/null 2>&1; then
  echo "[ERROR] conda command not found."
  exit 1
fi

CONDA_BASE="$(conda info --base)"
# shellcheck disable=SC1091
source "${CONDA_BASE}/etc/profile.d/conda.sh"

# 避免 conda activate.d 里未定义变量触发 unbound variable
set +u
conda activate "${CONDA_ENV}"
set -u

mkdir -p "${OUTPUT_DIR}"
mkdir -p "${LOG_DIR}"

echo "[INFO] Conda env: ${CONDA_ENV}"
echo "[INFO] Output dir: ${OUTPUT_DIR}"
echo "[INFO] Log dir: ${LOG_DIR}"
echo "[INFO] Max retries: ${MAX_RETRIES}"
echo "[INFO] Retry sleep: ${RETRY_SLEEP}s"
echo

########################################
# Validate files
########################################

for benchmark_file in "${BENCHMARK_FILES[@]}"; do
  if [ ! -f "${benchmark_file}" ]; then
    echo "[ERROR] Benchmark file not found: ${benchmark_file}"
    exit 1
  fi
done

########################################
# Run
########################################

FAILED_JOBS=()

run_one_job() {
  local provider="$1"
  local model_name="$2"
  local benchmark_path="$3"

  local benchmark_base
  benchmark_base="$(basename "${benchmark_path}")"
  benchmark_base="${benchmark_base%.*}"

  local safe_model
  safe_model="$(echo "${model_name}" | sed 's#[/ ]#_#g')"

  local timestamp
  timestamp="$(date +"%Y%m%d_%H%M%S")"

  local log_file="${LOG_DIR}/${provider}_${safe_model}_${benchmark_base}_${timestamp}.log"

  echo "========================================"
  echo "[INFO] Provider: ${provider}"
  echo "[INFO] Model: ${model_name}"
  echo "[INFO] Benchmark: ${benchmark_path}"
  echo "[INFO] Log: ${log_file}"
  echo "========================================"

  python -m "${RUNNER_MODULE}" \
    --provider "${provider}" \
    --model_name "${model_name}" \
    --benchmark_path "${benchmark_path}" \
    --output_dir "${OUTPUT_DIR}" \
    --temperature "${TEMPERATURE}" \
    --max_new_tokens "${MAX_NEW_TOKENS}" \
    --max_retries "${MAX_RETRIES}" \
    --retry_sleep "${RETRY_SLEEP}" \
    --report \
    2>&1 | tee "${log_file}"

  echo "[INFO] Finished: ${provider} / ${model_name} / ${benchmark_path}"
  echo
}

for model_entry in "${MODELS[@]}"; do
  IFS="|" read -r provider model_name <<< "${model_entry}"

  for benchmark_path in "${BENCHMARK_FILES[@]}"; do
    job_name="${provider}|${model_name}|${benchmark_path}"

    if run_one_job "${provider}" "${model_name}" "${benchmark_path}"; then
      echo "[SUCCESS] ${job_name}"
    else
      echo "[FAILED] ${job_name}"
      FAILED_JOBS+=("${job_name}")
    fi

    echo
  done
done

########################################
# Summary
########################################

echo "========================================"
echo "[SUMMARY]"
echo "========================================"

if [ "${#FAILED_JOBS[@]}" -eq 0 ]; then
  echo "All jobs finished successfully."
else
  echo "Some jobs failed:"
  for job in "${FAILED_JOBS[@]}"; do
    echo " - ${job}"
  done
  exit 1
fi