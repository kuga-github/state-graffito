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

CONFIG_ABS_PATH="$(realpath "${CONFIG_ABS_PATH}")"
WORK_DIR="$(dirname "${CONFIG_ABS_PATH}")"
export LOCAL_UID="$(id -u)"
export LOCAL_GID="$(id -g)"

if [[ -n "${GOOGLE_APPLICATION_CREDENTIALS:-}" ]]; then
    if [[ ! -f "${GOOGLE_APPLICATION_CREDENTIALS}" ]]; then
        echo "[ERROR] GOOGLE_APPLICATION_CREDENTIALS のファイルがありません。" >&2
        exit 1
    fi
    CREDENTIALS_PATH="$(realpath "${GOOGLE_APPLICATION_CREDENTIALS}")"
elif [[ -f "${HOME}/.config/gcloud/application_default_credentials.json" ]]; then
    CREDENTIALS_PATH="${HOME}/.config/gcloud/application_default_credentials.json"
else
    CREDENTIALS_PATH=""
fi

RUN_ARGS=(run --build --rm --no-deps)
RUN_ARGS+=(-v "${WORK_DIR}:/workspace/work")
if [[ -n "${CREDENTIALS_PATH}" ]]; then
    RUN_ARGS+=(
        -v "${CREDENTIALS_PATH}:/run/secrets/google-application-credentials.json:ro"
        -e GOOGLE_APPLICATION_CREDENTIALS=/run/secrets/google-application-credentials.json
    )
fi

echo "[INFO] MySQLを起動しています..."
docker compose -f "${COMPOSE_FILE}" up -d --wait db
echo "[INFO] 統合タグ生成パイプラインを実行しています..."
docker compose -f "${COMPOSE_FILE}" "${RUN_ARGS[@]}" tag_pipeline \
    "/workspace/work/$(basename "${CONFIG_ABS_PATH}")"
if [[ ! -s "${WORK_DIR}/tag.json" ]]; then
    echo "[ERROR] パイプライン出力が見つかりません: ${WORK_DIR}/tag.json" >&2
    exit 1
fi
echo "[INFO] JSON: ${WORK_DIR}/tag.json"
echo "[INFO] PNG: ${WORK_DIR}/debug/selected-string.png"
if [[ ! -s "${WORK_DIR}/instruction.png" ]]; then
    echo "[ERROR] Instruction画像が見つかりません: ${WORK_DIR}/instruction.png" >&2
    exit 1
fi
echo "[INFO] PNG: ${WORK_DIR}/instruction.png"
