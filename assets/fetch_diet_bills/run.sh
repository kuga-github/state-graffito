#!/usr/bin/env bash
set -euo pipefail

ASSET_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${ASSET_DIR}/../.." && pwd)"
COMPOSE_FILE="${ROOT_DIR}/docker-compose.yml"

if ! command -v docker >/dev/null 2>&1; then
    echo "[ERROR] docker が必要です。" >&2
    exit 1
fi

if [[ ! -f "${ROOT_DIR}/.env" && -f "${ROOT_DIR}/.env.example" ]]; then
    cp "${ROOT_DIR}/.env.example" "${ROOT_DIR}/.env"
    echo "[INFO] .env を作成しました。共有環境では認証情報を変更してください。"
fi

mkdir -p "${ROOT_DIR}/exports"
export LOCAL_UID="$(id -u)"
export LOCAL_GID="$(id -g)"

echo "[INFO] MySQL を起動しています..."
docker compose -f "${COMPOSE_FILE}" up -d --wait db

echo "[INFO] DBテーブルをCSVに出力しています..."
docker compose -f "${COMPOSE_FILE}" run --build --rm --no-deps \
    --entrypoint python fetch_diet_bills /app/export_csv.py

echo "[INFO] fetch_diet_bills を実行しています..."
docker compose -f "${COMPOSE_FILE}" run --build --rm --no-deps fetch_diet_bills "$@"

echo "[INFO] 取得したDBテーブルをCSVに再出力しています..."
docker compose -f "${COMPOSE_FILE}" run --build --rm --no-deps \
    --entrypoint python fetch_diet_bills /app/export_csv.py
echo "[INFO] CSV: ${ROOT_DIR}/exports/"
