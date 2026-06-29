#!/usr/bin/env bash
# Agent Light 一键安装脚本
#
#   curl -fsSL https://raw.githubusercontent.com/lzwcyd/agent-light/master/install.sh | bash
#
# 可选环境变量：
#   AGENT_LIGHT_VERSION   指定版本 tag（如 v1.0.0），默认安装 latest Release
#   AGENT_LIGHT_HOME      安装根目录，默认 ~/.agent-light/app
#   AGENT_LIGHT_NO_START  设为 1 则只安装、不自动启动

set -euo pipefail

REPO="lzwcyd/agent-light"
VERSION="${AGENT_LIGHT_VERSION:-latest}"
INSTALL_ROOT="${AGENT_LIGHT_HOME:-$HOME/.agent-light/app}"

info()  { printf '\033[1;34m▸\033[0m %s\n' "$*"; }
ok()    { printf '\033[1;32m✓\033[0m %s\n' "$*"; }
fail()  { printf '\033[1;31m✗\033[0m %s\n' "$*" >&2; exit 1; }

# ── 环境检查 ─────────────────────────────────────────
[[ "$(uname -s)" == "Darwin" ]] || fail "Agent Light 仅支持 macOS"
command -v curl >/dev/null 2>&1 || fail "需要 curl"
command -v tar  >/dev/null 2>&1 || fail "需要 tar"

# ── 解析下载地址 ─────────────────────────────────────
if [[ "$VERSION" == "latest" ]]; then
  API="https://api.github.com/repos/$REPO/releases/latest"
else
  API="https://api.github.com/repos/$REPO/releases/tags/$VERSION"
fi

info "查询 Release：$VERSION"
META="$(curl -fsSL "$API")" || fail "无法获取 Release 信息，请确认版本 $VERSION 存在"

# 优先取自定义的 agent-light-*.tar.gz 资产；缺失时回退到 GitHub 自动源码包
ASSET_URL="$(printf '%s' "$META" \
  | grep -o '"browser_download_url": *"[^"]*agent-light-[^"]*\.tar\.gz"' \
  | head -n1 | sed 's/.*"browser_download_url": *"//; s/"$//')"

if [[ -z "$ASSET_URL" ]]; then
  ASSET_URL="$(printf '%s' "$META" \
    | grep -o '"tarball_url": *"[^"]*"' \
    | head -n1 | sed 's/.*"tarball_url": *"//; s/"$//')"
fi
[[ -n "$ASSET_URL" ]] || fail "未在 Release 中找到可下载的源码包"

RESOLVED_TAG="$(printf '%s' "$META" | grep -o '"tag_name": *"[^"]*"' | head -n1 | sed 's/.*"tag_name": *"//; s/"$//')"
ok "找到版本 ${RESOLVED_TAG:-$VERSION}"

# ── 下载并解压 ───────────────────────────────────────
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
info "下载源码包..."
curl -fsSL "$ASSET_URL" -o "$TMP/agent-light.tar.gz" || fail "下载失败"

mkdir -p "$INSTALL_ROOT"
info "解压到 $INSTALL_ROOT"
tar -xzf "$TMP/agent-light.tar.gz" -C "$INSTALL_ROOT"

# 解压后的顶层目录（git archive: agent-light-<ver>/；GitHub tarball: <repo>-<sha>/）
APP_DIR="$(find "$INSTALL_ROOT" -maxdepth 1 -type d -name '*agent-light*' -newer "$TMP" -print -quit)"
[[ -z "$APP_DIR" ]] && APP_DIR="$(ls -dt "$INSTALL_ROOT"/*/ 2>/dev/null | head -n1)"
[[ -n "$APP_DIR" && -f "$APP_DIR/run.sh" ]] || fail "解压后未找到 run.sh"
APP_DIR="${APP_DIR%/}"

chmod +x "$APP_DIR/run.sh"
ok "已安装到 $APP_DIR"

# ── 启动 ─────────────────────────────────────────────
if [[ "${AGENT_LIGHT_NO_START:-0}" == "1" ]]; then
  echo
  ok "安装完成（未自动启动）。启动命令："
  echo "    cd \"$APP_DIR\" && ./run.sh"
  exit 0
fi

echo
info "首次启动将创建虚拟环境并安装依赖..."
cd "$APP_DIR"
./run.sh

echo
ok "完成！若菜单栏无图标，请授予 辅助功能 权限后重试："
echo "    系统设置 → 隐私与安全性 → 辅助功能"
echo
echo "常用命令（在 $APP_DIR 下）："
echo "    ./run.sh stop      # 停止"
echo "    ./run.sh status    # 状态"
