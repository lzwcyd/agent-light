"""Print resolved tool paths and presence (for debugging / first-run check)."""

from __future__ import annotations

import sys
from pathlib import Path

from .constants import APP_DATA_DIR
from .settings import get_tool_paths
from .tool_paths import get_resolved_tool_paths, invalidate_tool_paths_cache
from .tool_presence import (
    TOOL_LABELS,
    format_available_tools_summary,
    format_missing_tools_summary,
    get_all_tool_presence,
)


def _status(path: str) -> str:
    p = Path(path)
    if p.is_file():
        return "file"
    if p.is_dir():
        return "dir"
    return "missing"


def main() -> int:
    invalidate_tool_paths_cache()

    configured = get_tool_paths()
    print("Agent Light — 路径自动检测")
    print("=" * 40)

    if configured:
        print("\n[settings.json 覆盖]")
        for key, value in configured.items():
            print(f"  {key}: {value}")
    else:
        print("\n[settings.json] 未配置（完全自动发现）")

    print(f"\n{format_available_tools_summary()}")
    missing = format_missing_tools_summary()
    if missing:
        print(missing)

    print("\n[解析路径]")
    for key, value in get_resolved_tool_paths().items():
        mark = {"file": "✓", "dir": "✓", "missing": "○"}[_status(value)]
        print(f"  {mark} {key}")
        print(f"      {value}")

    print("\n[工具检测详情]")
    for tool, presence in get_all_tool_presence().items():
        label = TOOL_LABELS.get(tool, tool)
        state = "已安装" if presence.available else "未检测到"
        print(f"  {label}: {state}")
        print(f"      {presence.reason}")
        if presence.config_dir:
            print(f"      config → {presence.config_dir}")

    available = [t for t, p in get_all_tool_presence().items() if p.available]
    if not available:
        print(
            "\n提示：未发现 AI 工具。安装 Cursor / Claude Code / Codex 后至少运行一次，"
            "或在 settings.json 配置 tool_paths（"
            f"{APP_DATA_DIR / 'settings.json'}）。",
            file=sys.stderr,
        )
        return 1

    print("\n✓ 路径自动检测完成，可直接 ./run.sh 启动并在菜单栏安装 Hook。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
