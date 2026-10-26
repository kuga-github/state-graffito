#!/usr/bin/env bash
set -euo pipefail

SERVICE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SERVICE_DIR}/../.." && pwd)"
COMPOSE_FILE="${ROOT_DIR}/docker-compose.yml"

if [[ $# -ne 1 ]]; then
    echo "[ERROR] 使用方法: $0 <config_yaml_path>" >&2
    echo "例: $0 works/WORK_NAME/WORK_VERSION/config.yaml" >&2
    exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
    echo "[ERROR] docker が必要です。" >&2
    exit 1
fi

CONFIG_ARG="$1"
if [[ "${CONFIG_ARG}" = /* ]]; then
    CONFIG_ABS_PATH="${CONFIG_ARG}"
else
    CONFIG_ABS_PATH="$(pwd)/${CONFIG_ARG}"
fi
if [[ ! -f "${CONFIG_ABS_PATH}" ]]; then
    echo "[ERROR] 設定ファイルが存在しません: ${CONFIG_ABS_PATH}" >&2
    exit 1
fi

WORK_DIR="$(cd "$(dirname "${CONFIG_ABS_PATH}")" && pwd)"
CONFIG_NAME="$(basename "${CONFIG_ABS_PATH}")"
export LOCAL_UID="$(id -u)"
export LOCAL_GID="$(id -g)"

echo "[INFO] 項目別スコアを計算しています..."
echo "[INFO] 設定: ${CONFIG_ABS_PATH}"
echo "[INFO] 入力JSON: ${WORK_DIR}/cabinet_llm.json"
docker compose -f "${COMPOSE_FILE}" run --build --rm --no-deps \
    -v "${WORK_DIR}:/workspace/work" \
    cabinet_score "/workspace/work/${CONFIG_NAME}"
echo "[INFO] JSON: ${WORK_DIR}/cabinet_score.json"
