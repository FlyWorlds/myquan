#!/usr/bin/env bash
# macOS / Linux：加载 Node 环境（若有）→ 启动 Python 数据 API + Web 盯盘
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

for hook in "$HOME/.openclaw/use-node24.sh" "$HOME/.openclaw/use-node24.zsh"; do
  if [[ -f "$hook" ]]; then
    # shellcheck disable=SC1090
    source "$hook"
    echo "[start_watch] loaded $(basename "$hook")"
    break
  fi
done

if ! command -v openclaw >/dev/null 2>&1 && [[ -s "$HOME/.nvm/nvm.sh" ]]; then
  # shellcheck disable=SC1091
  source "$HOME/.nvm/nvm.sh"
  nvm use 24 >/dev/null 2>&1 || nvm use default >/dev/null 2>&1 || true
fi

PY="${MYQUAN_PYTHON:-}"
if [[ -z "$PY" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    PY="$(command -v python3)"
  elif command -v python >/dev/null 2>&1; then
    PY="$(command -v python)"
  else
    echo "[start_watch] ERROR: python not found; set MYQUAN_PYTHON" >&2
    exit 1
  fi
fi

exec "$PY" "$ROOT/start_watch.py" "$@"
