# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Agent Light — self-contained macOS menu-bar .app.

构建：
    pyinstaller agent-light.spec
版本号经环境变量注入（CI 用 tag）：
    AGENT_LIGHT_VERSION=1.0.0 pyinstaller agent-light.spec
"""

import os

from PyInstaller.utils.hooks import collect_submodules

VERSION = os.environ.get("AGENT_LIGHT_VERSION", "0.0.0")

# PyObjC 动态属性常被静态分析漏收，显式补子模块；agent_light 兜底延迟 import
# （如 relay 链路、detector 里的延迟 import）。比 collect_all 体积小。
hiddenimports = []
for pkg in (
    "objc",
    "Foundation",
    "AppKit",
    "Quartz",
    "ApplicationServices",
    "CoreFoundation",
    "agent_light",
):
    hiddenimports += collect_submodules(pkg)

# assets 目标目录必须是 agent_light/assets：kun_silhouette.py 用
# Path(__file__).parent.parent / "assets" 定位，冻结后 __file__ 在
# _MEIPASS/agent_light/ui/ 下，parent.parent == _MEIPASS/agent_light。
datas = [("agent_light/assets", "agent_light/assets")]

a = Analysis(
    ["agent_light/main.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="agent-light",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # windowed —— 不影响 relay（hook 经 shell exec 调用，继承 fd）
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="agent-light",
)

app = BUNDLE(
    coll,
    name="Agent Light.app",
    icon=None,  # LSUIElement 应用 dock/启动台无图标，菜单栏图标走代码 emoji
    bundle_identifier="com.lzwcyd.agent-light",
    version=VERSION,
    info_plist={
        "LSUIElement": True,  # 启动即 accessory，避免 dock 图标闪现
        "CFBundleName": "Agent Light",
        "CFBundleDisplayName": "Agent Light",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "12.0",
    },
)
