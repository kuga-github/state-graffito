#!/usr/bin/env bash
set -euo pipefail

if (($# > 0)); then
    echo "使い方: $0" >&2
    exit 2
fi

ASSET_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${ASSET_DIR}/../.." && pwd)"
COMPOSE_FILE="${ROOT_DIR}/docker-compose.yml"
APP_DIR="${ASSET_DIR}"

for tool in docker node npm; do
    if ! command -v "${tool}" >/dev/null 2>&1; then
        echo "[ERROR] ${tool} が必要です。" >&2
        exit 1
    fi
done

if [[ ! -f "${ROOT_DIR}/.env" && -f "${ROOT_DIR}/.env.example" ]]; then
    cp "${ROOT_DIR}/.env.example" "${ROOT_DIR}/.env"
    echo "[INFO] .env を作成しました。共有環境では認証情報を変更してください。"
fi

if [[ ! -x "${APP_DIR}/node_modules/.bin/next" ]]; then
    echo "[INFO] Next.js の依存関係をホストにインストールします..."
    (cd "${APP_DIR}" && npm ci)
fi

mkdir -p "${ROOT_DIR}/exports"
export LOCAL_UID="$(id -u)"
export LOCAL_GID="$(id -g)"

echo "[INFO] MySQL と generate_char_path を起動しています..."
docker compose -f "${COMPOSE_FILE}" up --build -d --wait db web

echo "[INFO] DBテーブルをCSVに出力しています..."
docker compose -f "${COMPOSE_FILE}" run --build --rm --no-deps \
    --entrypoint python fetch_cabinet_info /app/export_csv.py
echo "[INFO] http://localhost:3000 で利用できます。CSV: ${ROOT_DIR}/exports/"
