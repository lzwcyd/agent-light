#!/usr/bin/env bash
# Agent Light 一键安装脚本（免本机 Python）
#
#   curl -fsSL https://raw.githubusercontent.com/lzwcyd/agent-light/master/install.sh | bash
#
# 下载对应架构的自包含二进制（内嵌 Python + 依赖），装到 ~/.agent-light/bin
# 并软链到 ~/.local/bin，随后后台启动。
#
# 可选环境变量：
#   AGENT_LIGHT_VERSION   指定版本 tag（如 v1.0.0），默认 latest
#   AGENT_LIGHT_NO_START  设为 1 则只安装、不自动启动

set -euo pipefail

REPO="${AGENT_LIGHT_REPO:-lzwcyd/agent-light}"
VERSION="${AGENT_LIGHT_VERSION:-latest}"
INSTALL_DIR="${AGENT_LIGHT_INSTALL_DIR:-$HOME/.agent-light/bin}"
BIN_DIR="${AGENT_LIGHT_BIN_DIR:-$HOME/.local/bin}"

info()  { printf '\033[1;34m▸\033[0m %s\n' "$*"; }
ok()    { printf '\033[1;32m✓\033[0m %s\n' "$*"; }
fail()  { printf '\033[1;31m✗\033[0m %s\n' "$*" >&2; exit 1; }

# ── 环境检查 ─────────────────────────────────────────
[[ "$(uname -s)" == "Darwin" ]] || fail "Agent Light 仅支持 macOS"
command -v curl >/dev/null 2>&1 || fail "需要 curl"
command -v tar  >/dev/null 2>&1 || fail "需要 tar"

# ── 按架构选择资产 ───────────────────────────────────
ARCH="$(uname -m)"
case "$ARCH" in
  arm64|aarch64) ASSET="agent-light-macos-arm64.tar.gz" ;;
  x86_64|amd64)  ASSET="agent-light-macos-x64.tar.gz" ;;
  *) fail "不支持的架构：$ARCH" ;;
esac

if [[ "$VERSION" == "latest" ]]; then
  URL="https://github.com/$REPO/releases/latest/download/$ASSET"
else
  URL="https://github.com/$REPO/releases/download/$VERSION/$ASSET"
fi

# ── 下载并解压 ───────────────────────────────────────
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

info "下载 $ASSET（$VERSION）"
curl --retry 5 --retry-delay 2 -fsSL "$URL" -o "$TMP/$ASSET" \
  || fail "下载失败，请确认版本 $VERSION 存在：https://github.com/$REPO/releases"

info "解压并安装到 $INSTALL_DIR"
mkdir -p "$INSTALL_DIR" "$BIN_DIR"
tar -xzf "$TMP/$ASSET" -C "$INSTALL_DIR"
[[ -f "$INSTALL_DIR/agent-light" ]] || fail "解压后未找到 agent-light 二进制"

chmod +x "$INSTALL_DIR/agent-light"
# 放行未签名二进制的 Gatekeeper 隔离属性
xattr -dr com.apple.quarantine "$INSTALL_DIR/agent-light" 2>/dev/null || true

ln -sf "$INSTALL_DIR/agent-light" "$BIN_DIR/agent-light"
ok "已安装：$BIN_DIR/agent-light"

# ── 启动 ─────────────────────────────────────────────
if [[ "${AGENT_LIGHT_NO_START:-0}" == "1" ]]; then
  echo
  ok "安装完成（未自动启动）。启动命令："
  echo "    agent-light"
  exit 0
fi

PID_FILE="$HOME/.agent-light/agent-light.pid"
if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  info "检测到已在运行，先停止旧进程"
  kill -TERM "$(cat "$PID_FILE")" 2>/dev/null || true
  sleep 1
fi

info "后台启动 Agent Light..."
nohup "$INSTALL_DIR/agent-light" --quiet > /dev/null 2>&1 &
sleep 1.2

if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  ok "已启动 (PID $(cat "$PID_FILE"))"
else
  info "进程未确认启动——可能在等待辅助功能授权（见下方）"
fi

echo
ok "完成！如果菜单栏没有图标，请授予 辅助功能 权限后重新运行 agent-light："
echo "    系统设置 → 隐私与安全性 → 辅助功能 → 添加并勾选 agent-light"
open "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility" 2>/dev/null || true
echo
echo "常用命令："
echo "    agent-light            # 启动（前台，Ctrl+C 退出）"
echo "    安装 Hook 请用菜单栏 →「安装 Hook」"

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *)
    echo
    info "$BIN_DIR 不在 PATH 中，请加入 shell 配置："
    echo "    export PATH=\"$BIN_DIR:\$PATH\""
    ;;
esac
