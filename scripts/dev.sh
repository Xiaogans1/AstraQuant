#!/usr/bin/env bash
# AstraQuant development launcher for macOS and Linux.
# Mirrors scripts/dev.ps1: syncs dependencies and starts the Tauri desktop app.

set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
skip_sync=0
for arg in "$@"; do
    if [ "$arg" = "--skip-sync" ] || [ "$arg" = "-s" ]; then
        skip_sync=1
    fi
done

cd "$project_root"

for command_name in uv node npm cargo; do
    if ! command -v "$command_name" >/dev/null 2>&1; then
        echo "Required development command is missing: $command_name" >&2
        exit 1
    fi
done

if ! command -v pnpm >/dev/null 2>&1 && ! command -v corepack >/dev/null 2>&1; then
    echo "pnpm and Node.js Corepack are both missing; reinstall Node.js 24 or newer" >&2
    exit 1
fi

if [ "$skip_sync" -eq 0 ]; then
    if [ ! -d "$project_root/.venv" ]; then
        uv sync --locked --all-packages
    fi

    if [ ! -d "$project_root/node_modules" ]; then
        pnpm install --frozen-lockfile
    fi
fi

npm --prefix apps/desktop run tauri -- dev
