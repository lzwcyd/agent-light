#!/bin/bash
# Agent Light launcher for macOS

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PID_FILE="$HOME/.agent-light/agent-light.pid"
LOG_FILE="$HOME/.agent-light/logs/agent-light.log"

# ── stop ──────────────────────────────────────────────
if [[ "${1:-}" == "stop" ]]; then
  if [[ -f "$PID_FILE" ]]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
      mkdir -p "$HOME/.agent-light"
      echo stop > "$HOME/.agent-light/shutdown.request"
      kill -TERM "$PID" 2>/dev/null || true
      echo "✓ 已发送停止请求 (PID $PID)"
      for _ in 1 2 3 4 5 6; do
        kill -0 "$PID" 2>/dev/null || { echo "✓ Agent Light 已关闭"; rm -f "$HOME/.agent-light/shutdown.request"; exit 0; }
        sleep 0.5
      done
      echo "⚠ 进程未响应，强制终止..."
      kill -9 "$PID" 2>/dev/null || true
      rm -f "$PID_FILE" "$HOME/.agent-light/shutdown.request"
    else
      echo "进程 $PID 已不存在，清理 PID 文件"
      rm -f "$PID_FILE"
    fi
  else
    echo "Agent Light 未在运行"
  fi
  exit 0
fi

if [[ "${1:-}" == "status" ]]; then
  if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "✓ Agent Light 运行中 (PID $(cat "$PID_FILE"))"
    if [[ -f "$LOG_FILE" ]]; then
      echo "  日志: $LOG_FILE"
    else
      echo "  日志: 未启用（默认静默模式，使用 ./run.sh verbose 可写日志）"
    fi
  else
    echo "✗ Agent Light 未运行"
  fi
  exit 0
fi

# ── logs ──────────────────────────────────────────────
if [[ "${1:-}" == "logs" ]]; then
  if [[ -f "$LOG_FILE" ]]; then
    tail -f "$LOG_FILE"
  else
    echo "日志文件不存在（默认静默模式未写日志）"
    echo "请使用 ./run.sh verbose 启动以启用日志，或查看 ./run.sh status"
    exit 1
  fi
  exit 0
fi

# ── verbose start ─────────────────────────────────────
VERBOSE_FLAG=""
if [[ "${1:-}" == "verbose" || "${1:-}" == "--verbose" || "${1:-}" == "-v" ]]; then
  VERBOSE_FLAG="--verbose"
  shift
fi

# ── start ─────────────────────────────────────────────
PYTHON=""
for candidate in python3.12 python3.11 python3.10 python3.9 python3; do
  if command -v "$candidate" >/dev/null 2>&1 \
    && "$candidate" -c 'import sys; exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
    PYTHON="$candidate"
    break
  fi
done

if [[ -z "$PYTHON" ]]; then
  echo "✗ 未找到 Python 3.9+，请先安装 Python"
  exit 1
fi

VENV_PY="$SCRIPT_DIR/.venv/bin/python"

venv_is_valid() {
  [[ -x "$VENV_PY" ]] && "$VENV_PY" -c 'import sys; exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null
}

ensure_venv() {
  if venv_is_valid; then
    return 0
  fi
  if [[ -d ".venv" ]]; then
    echo "检测到无效的虚拟环境（可能从其他电脑复制），正在用本机 Python 重建..."
    rm -rf .venv
  else
    echo "首次运行，正在创建虚拟环境..."
  fi
  echo "  使用: $($PYTHON -c 'import sys; print(sys.executable)' 2>/dev/null || echo "$PYTHON")"
  "$PYTHON" -m venv .venv
  if ! venv_is_valid; then
    echo "✗ 虚拟环境创建失败，请确认本机 Python 可用: $PYTHON --version"
    exit 1
  fi
  "$VENV_PY" -m pip install --upgrade pip setuptools -q
  "$VENV_PY" -m pip install -e . -q
  echo "✓ 依赖安装完成"
}

ensure_venv

if [[ "${1:-}" == "install-cursor-hooks" || "${1:-}" == "install-hooks" ]]; then
  exec "$VENV_PY" -m agent_light.agent_hooks.install
fi

if [[ "${1:-}" == "uninstall-hooks" ]]; then
  exec "$VENV_PY" -m agent_light.agent_hooks.install --uninstall
fi

if [[ "${1:-}" == "paths" ]]; then
  exec "$VENV_PY" -m agent_light.path_check
fi

if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "Agent Light 已在运行 (PID $(cat "$PID_FILE"))"
  echo "  停止: ./run.sh stop"
  echo "  状态: ./run.sh status"
  exit 0
fi

check_accessibility() {
  "$VENV_PY" - <<'PY'
import subprocess
result = subprocess.run(
    ["osascript", "-e", 'tell application "System Events" to return name of first process'],
    capture_output=True, text=True
)
if result.returncode != 0:
    raise SystemExit(1)
PY
}

if ! check_accessibility 2>/dev/null; then
  echo "⚠️  需要辅助功能权限 (Accessibility)"
  echo "   系统设置 → 隐私与安全性 → 辅助功能 → 添加 Terminal"
  open "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility" 2>/dev/null || true
fi

if [[ -n "$VERBOSE_FLAG" ]]; then
  echo "启动 Agent Light（日志模式）..."
  echo "  关闭: ./run.sh stop  |  菜单栏图标 → 退出  |  面板 ✕  |  Ctrl+C"
  echo "  日志: $LOG_FILE"
  echo ""
  exec "$VENV_PY" -m agent_light.main --verbose "$@"
fi

nohup "$VENV_PY" -m agent_light.main --quiet "$@" > /dev/null 2>&1 &
sleep 0.8
if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "✓ Agent Light 已启动 (PID $(cat "$PID_FILE"))"
  echo "  停止: ./run.sh stop"
  echo "  状态: ./run.sh status"
  echo "  调试: ./run.sh verbose"
else
  echo "✗ 启动失败，请运行 ./run.sh verbose 查看错误信息"
  exit 1
fi
