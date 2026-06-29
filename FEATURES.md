# Agent Light — 功能全览与问题检测

> 本文档汇总项目**全部功能**、**数据流**、**命令与配置**，并记录当前已知问题与改进建议。  
> 面向开发者与新用户；快速上手见 [README.md](README.md)。

---

## 目录

1. [产品概述](#1-产品概述)
2. [启动与命令](#2-启动与命令)
3. [核心监控](#3-核心监控)
4. [Agent Hooks](#4-agent-hooks)
5. [路径自动发现](#5-路径自动发现)
6. [菜单栏与悬浮面板](#6-菜单栏与悬浮面板)
7. [显示模式与自定义风格](#7-显示模式与自定义风格)
8. [点击聚焦](#8-点击聚焦)
9. [配置与持久化](#9-配置与持久化)
10. [项目结构](#10-项目结构)
11. [架构与数据流](#11-架构与数据流)
12. [问题检测报告](#12-问题检测报告)

---

## 1. 产品概述

**Agent Light** 是 macOS 菜单栏 + 悬浮面板应用，监控 AI 工具运行状态：

| 状态 | 交通灯 | 含义 |
|------|--------|------|
| 运行中 | 🔴 | Agent 正在生成、执行工具 |
| 人工确认 | 🟡 | 权限确认、Run Command、AskQuestion 等 |
| 结束 | 🟢 | 空闲 / 任务完成 / 用户中断 |

**监控对象（Hook 模式）**

| 工具 | 实例粒度 | 状态来源 |
|------|----------|----------|
| Cursor | 每个窗口 | Agent Hooks |
| Claude Code（CLI） | 每个终端会话 | Agent Hooks |
| Codex（CLI） | 每个终端会话 | Agent Hooks |
| Claude Desktop（GUI） | 每个窗口 | **Accessibility 窗口文本**（无 Hook） |

**系统要求**：macOS 12+、Python 3.9+、辅助功能权限。

**用户数据目录**：`~/.agent-light/`（不随仓库分发）

---

## 2. 启动与命令

**推荐入口**：`./run.sh`（项目根目录）

| 命令 | 说明 |
|------|------|
| `./run.sh` | 默认：创建/校验 `.venv` → 安装依赖 → 后台静默启动 |
| `./run.sh verbose` | 前台运行 + 写日志 |
| `./run.sh stop` | 停止（写 shutdown 标志 + SIGTERM） |
| `./run.sh status` | 是否在运行 |
| `./run.sh logs` | `tail -f` 日志（需 verbose 模式写过日志） |
| `./run.sh paths` | 检测本机 AI 工具路径与安装情况 |
| `./run.sh install-hooks` | 安装 Agent Hooks |
| `./run.sh uninstall-hooks` | 删除 Agent Light 的 Hooks |
| `./run.sh install-cursor-hooks` | 旧别名，等同 `install-hooks` |

**CLI 入口**（手动安装后）：`agent-light` / `agent-light --verbose`

**首次运行自动完成**

1. 检测 Python 3.9+
2. 无效 `.venv` 自动重建（换电脑勿复制 `.venv`）
3. `pip install -e .`
4. 检测辅助功能权限（失败则打开系统设置）
5. 后台启动，菜单栏出现图标

**轮询间隔**：1.5 秒（`main.py` `POLL_INTERVAL`）

---

## 3. 核心监控

### 3.1 实例发现（`detector/process_scanner.py` + `cli_tool_scanner.py`）

**Cursor**

- 解析 extension-host 子进程命令行：`extension-host (…) <workspace> [windowIndex-id]`
- 回退：Accessibility 窗口标题
- 工作区路径：`workspace_resolver.py`（hooks 日志 + `workspaceStorage`）

**Claude Code / Codex（CLI）**

- 匹配 node / 原生二进制进程
- 按 TTY 去重，追溯终端/shell 父进程
- 支持检测的终端：iTerm、Terminal、Warp、Alacritty、Kitty

**Claude Desktop（GUI）**

- Bundle ID：`com.anthropic.claudefordesktop`、`com.anthropic.claude`
- 出现在面板上，但**不参与 Hook 安装**

### 3.2 状态分析（`detector/state_analyzer.py`）

| 工具类型 | 分析方式 |
|----------|----------|
| `cursor` | `cursor_hook_monitor` → `agent_hooks/store.lookup_state` |
| `codex`、`claude-code` | `cli_hook_monitor` → `lookup_state` |
| 其他 GUI（含 Claude Desktop） | Accessibility 窗口文本正则（`UI: …`） |

**无 Hook 信号时**：Cursor / CLI 默认 **🟢 idle**（`hook: idle`）

**Hook 状态映射**（`agent_hooks/state_map.py`）

- 运行：`preToolUse`、`postToolUse`、`userPromptSubmit` 等 → 🔴
- 等待：`permissionRequest`、`beforeShellExecution`、`AskQuestion` 等 → 🟡
- 结束：`stop`、`sessionEnd`、用户中断 → 🟢

**信号存储**：`~/.agent-light/agent-hooks/states/{tool}-{workspace-slug}.json`

**信号 TTL**（过期后视为无信号 → 绿灯）

| 状态 | TTL |
|------|-----|
| running | 35 秒 |
| waiting | 600 秒 |
| idle | 86400 秒 |

### 3.3 辅助检测模块

| 文件 | 用途 |
|------|------|
| `detector/cursor_log_utils.py` | 读取 Cursor 日志目录（工作区 / 会话 ID 解析） |
| `detector/cli_session_monitor.py` | Claude Desktop Hook fallback：会话 JSONL |

---

## 4. Agent Hooks

### 4.1 安装目标

| 工具 | 配置文件 | 脚本 |
|------|----------|------|
| Cursor | `~/.cursor/hooks.json` | `~/.cursor/hooks/agent-light-signal.sh` |
| Claude Code | `~/.claude/settings.json` | `~/.claude/hooks/agent-light-claude-signal.sh` |
| Codex | `~/.codex/hooks.json` | `~/.codex/hooks/agent-light-codex-signal.sh` |

中继：`python -m agent_light.agent_hooks.relay`（stdin JSON → 写状态文件）

Python 路径缓存：`~/.agent-light/agent-hooks/python.txt`

### 4.2 菜单栏操作

- **安装 Hook**：增量安装（见下）
- **删除 Hook**：移除所有已安装的 Agent Light Hook（不影响用户其他 Hook）
- **首次提醒**：未装 Hook 时弹窗（立即安装 / 稍后 / 不再提醒）

菜单进度示例：`安装 Hook (1/2)`、`安装 Hook ✓`

### 4.3 增量安装逻辑（`agent_hooks/install.py`）

1. 刷新路径缓存，检测本机已安装工具（`tool_presence`）
2. 未检测到的工具 → **跳过**
3. 已检测 + 配置完整 → **跳过**（显示「已安装且配置完整」）
4. 部分缺失 → **修复并校验**
5. 新工具 → **安装**
6. 合并写入配置，**不覆盖**用户原有 Hook 条目
7. 删除时只移除 `agent-light-*.sh` 及对应配置项

### 4.4 完整性校验（`_audit_tool_hooks`）

- 脚本存在、可执行、含 `agent_light.agent_hooks.relay`
- 全部必需 Hook 事件已注册
- Codex：`config.toml` 中 `hooks = false` 会报错

### 4.5 向后兼容

- 旧状态目录：`~/.agent-light/cursor-hooks/states/`
- 旧 python.txt：`~/.agent-light/cursor-hooks/python.txt`

---

## 5. 路径自动发现

### 5.1 优先级

```
settings.json (tool_paths)
  → 环境变量 (AGENT_LIGHT_* / CODEX_HOME / …)
    → 运行中进程探测
      → 默认路径
```

### 5.2 默认探测

| 工具 | 探测方式 |
|------|----------|
| Cursor | `~/Library/Application Support/Cursor`、Nightly、`--user-data-dir`、Cursor.app |
| Claude Code | `~/.claude`、`which claude`、`~/.local/bin`、Homebrew Cask |
| Codex | `~/.codex`、`which codex`、Homebrew Cask |

**无需软件正在运行**即可检测是否安装（`tool_presence.py`）。

### 5.3 自检

```bash
./run.sh paths
```

输出：settings 覆盖、解析路径（✓/○）、各工具检测原因。

---

## 6. 菜单栏与悬浮面板

### 6.1 菜单栏（`main.py`）

| 菜单项 | 功能 |
|--------|------|
| 显示面板 | 面板置前 |
| 🚦 交通灯 | 经典三灯 |
| 我爱坤坤💗💗 | 内置 GIF 样式 |
| {emoji} 风格名 | 已保存自定义风格 |
| 我爱发明 | 风格管理窗口 |
| 安装 Hook / 删除 Hook | Hook 管理 |
| 关于 | 版本说明 |
| 打开日志 | 仅 verbose 模式显示 |
| 退出 Agent Light | 完全退出（快捷键 q） |

应用为 **Accessory** 模式（无 Dock 图标）。

### 6.2 悬浮面板（`ui/traffic_light_panel.py`）

- 无边框、置顶、全 Space / 全屏可见
- 可拖动空白区域移动
- 无实例时显示「等待 AI 工具…」
- **✕ 按钮 = 退出整个应用**（非仅隐藏）
- 每次轮询会 `orderFrontRegardless()`（保持可见）

---

## 7. 显示模式与自定义风格

### 7.1 内置模式

| 模式 | settings 值 | 实现 |
|------|-------------|------|
| 交通灯 | `traffic` | 三圆点 CALayer |
| 坤坤 | `kun` | `assets/kun.gif`、`kun_waiting.gif`、`kun_done.jpg` |
| 自定义 | `custom:{id}` | 用户上传图片/GIF |

### 7.2 我爱发明（`ui/style_manager_window.py`）

- 新增 / 删除 / 保存风格
- 必填：名称、Banner emoji、运行中/等待/结束 三张图
- Pillow 自动缩放至 80×88
- 未完成风格不出现在菜单

存储：

- `~/.agent-light/custom_styles.json`
- `~/.agent-light/styles/{id}/`

---

## 8. 点击聚焦

**入口**：点击面板卡片 → `focus.py` → `focus_instance`

| 工具 | 策略 |
|------|------|
| Cursor | AppleScript 按窗口标题 → AX → 进程 → 激活 Bundle |
| Claude Code / Codex | iTerm 会话名匹配 → Terminal/iTerm 激活 |
| Claude Desktop 等 GUI | Bundle → AX 窗口 → 进程 |

**Bundle ID**：Cursor 硬编码 `com.todesktop.230313mzl4w4u92`

聚焦失败仅写日志，**无 UI 提示**。

---

## 9. 配置与持久化

### 9.1 `~/.agent-light/` 目录

```
~/.agent-light/
├── settings.json           # display_mode, tool_paths, hooks_reminder_dismissed
├── custom_styles.json
├── styles/{id}/
├── agent-hooks/
│   ├── states/             # Hook 状态 JSON
│   └── python.txt
├── logs/agent-light.log    # verbose 模式
├── agent-light.pid
└── shutdown.request        # ./run.sh stop 使用
```

### 9.2 settings.json 字段

| 字段 | 说明 |
|------|------|
| `display_mode` | `traffic` / `kun` / `custom:{id}` |
| `tool_paths` | 可选路径覆盖（见 README） |
| `hooks_reminder_dismissed` | 是否不再提醒安装 Hook |

旧版 `kun_mode: true` 会自动迁移为 `display_mode: "kun"`。

### 9.3 日志

- 默认静默（NullHandler）
- verbose：1MB 轮转 × 2 备份 + 控制台

---

## 10. 项目结构

```
agent-light/
├── run.sh                      # 推荐入口
├── pyproject.toml
├── README.md                   # 快速上手
├── FEATURES.md                 # 本文档
├── agent_light/
│   ├── main.py                 # 应用入口、菜单、轮询
│   ├── constants.py            # 应用名、数据目录
│   ├── settings.py             # 用户偏好
│   ├── styles.py               # 自定义风格 CRUD
│   ├── focus.py                # 点击聚焦
│   ├── tool_paths.py           # 路径解析
│   ├── tool_presence.py        # 工具是否安装
│   ├── path_check.py           # ./run.sh paths
│   ├── logging_config.py
│   ├── shutdown.py
│   ├── models.py
│   ├── agent_hooks/            # Hook 安装、relay、状态映射、store
│   ├── detector/               # 扫描、状态分析
│   ├── ui/                     # 面板、风格管理、坤坤
│   └── assets/                 # kun GIF 等
```

---

## 11. 架构与数据流

```
┌─────────────────────────────────────────────────────────┐
│  main.py (每 1.5s)                                       │
│    scan_instances()                                      │
│      ├─ process_scanner  → Cursor, Claude Desktop       │
│      └─ cli_tool_scanner → Claude Code, Codex           │
│    analyze_states()                                      │
│      ├─ cursor/claude-code/codex → hook store lookup    │
│      └─ claude-desktop → hook + session fallback        │
│    traffic_light_panel.update()                          │
└─────────────────────────────────────────────────────────┘

Agent Hooks 侧链：
  AI 工具 hook 事件
    → agent-light-*.sh
    → agent_light.agent_hooks.relay
    → ~/.agent-light/agent-hooks/states/*.json
    → lookup_state() ← analyze_states()
```

---

## 12. 问题检测报告

检测时间：基于当前代码库静态审查 + 本机 `./run.sh paths` / import 验证。

### 12.1 功能正常 ✅

| 项 | 状态 |
|----|------|
| `./run.sh` 一键启动（venv + 依赖 + 后台） | ✅ |
| 路径全自动发现（无 settings.json） | ✅ 本机已验证 |
| `./run.sh paths` 自检 | ✅ |
| Hook 增量安装 / 删除 / 不覆盖原 Hook | ✅ |
| Cursor / Claude Code / Codex Hook 状态 | ✅（需已安装 Hook） |
| 交通灯 / 坤坤 / 自定义风格切换 | ✅ |
| 菜单栏 Hook 管理 + 首次提醒 | ✅ |
| 辅助功能权限检测 | ✅ |
| Python 包导入与编译 | ✅ |

### 12.2 已知问题（按优先级）

#### 🔴 高 — 影响用户理解或核心体验

| # | 问题 | 说明 | 相关文件 |
|---|------|------|----------|
| H1 | **未装 Hook 永远绿灯** | Cursor / CLI 无信号时固定 `hook: idle`，易误以为「监控正常」 | `state_analyzer.py` |
| H2 | ~~**Claude 两套产品混淆**~~ | **已缓解**：卡片区分 Desktop / CLI；Desktop 编程模式走 Hook（见 README） | `process_scanner.py`, `state_analyzer.py`, `claude_desktop_*` |
| H3 | **README 表述不精确** | 「不会盲目创建目录」— Hook **安装时**仍会为已检测工具 `mkdir` 配置目录 | `README.md`, `install.py` |

#### 🟡 中 — 特定场景下体验不佳

| # | 问题 | 说明 | 相关文件 |
|---|------|------|----------|
| M1 | ~~**同工作区多窗口共享 Hook 状态**~~ | **已修复**：按 `conversation_id` 分文件 + 从窗口 hook 日志解析会话 | `store.py`, `cursor_window_conversations.py` |
| M2 | **Running TTL 仅 35 秒** | 长时间无新 Hook 事件时，运行中可能短暂变绿 | `agent_hooks/store.py` |
| M3 | **Warp / Kitty / Alacritty 聚焦弱** | CLI 扫描能识别，聚焦主要支持 iTerm / Terminal | `focus.py`, `cli_tool_scanner.py` |
| M4 | **面板每 1.5s 强制置前** | 用户手动把面板移到后面会被拉回 | `traffic_light_panel.py` |
| M5 | **面板 ✕ = 退出应用** | 非「隐藏面板」，易误触退出 | `traffic_light_panel.py`, `main.py` |
| M6 | **聚焦失败无提示** | 点击卡片无反应时用户不知情 | `focus.py` |
| M7 | **无工具时仍可启动** | `./run.sh paths` 返回 1，但 `./run.sh` 仍会启动空面板 | `run.sh`, `path_check.py` |

#### 🟢 低 — 代码卫生 / 文档 / 边缘情况

| # | 问题 | 说明 | 相关文件 |
|---|------|------|----------|
| L1 | ~~**遗留 monitor 未删除**~~ | **已清理**：移除 log/transcript monitor 与 `cursor_hooks` shim | — |
| L2 | ~~**未使用的函数**~~ | **已清理**：`stop_running_instance`、`get_resolved_tool_presence`、kun mode 包装等 | — |
| L3 | **README 缺命令** | `./run.sh logs`、`install-cursor-hooks` 未写入命令表 | `README.md` |
| L4 | ~~**cursor_hooks 兼容层**~~ | **已移除**；请使用 `agent_light.agent_hooks` | — |
| L5 | **settings 无 UI** | `tool_paths` 只能手改 JSON | `settings.py` |
| L6 | **kun 未用资源** | `kun.webp`、`kun_idle.png` 未引用 | `assets/` |
| L7 | **invalid settings.json** | 解析失败静默回退默认，无用户提示 | `settings.py` |
| L8 | **tick 异常** | 轮询失败只打日志，面板可能显示旧状态 | `main.py` |

### 12.3 文档与代码不一致

| 文档说法 | 实际情况 |
|----------|----------|
| 监控 Cursor / Claude Code / Codex | 还监控 **Claude Desktop 编程模式** |
| 状态来自 Agent Hooks | Desktop 普通聊天无 Hook；编程模式与 CLI 同源 |
| 三个工具都要装 | **支持只装部分**，增量安装 |
| `./run.sh` 即可 | 还需 **辅助功能权限** + **安装 Hook** 才有准确状态 |

### 12.4 建议改进（未实施）

1. **H1**：未装 Hook 时菜单常驻提示或面板显示「请安装 Hook」
2. ~~**H2**：Claude Desktop 卡片标注~~ → 已实现 Hook 路径 + README 注意点
3. **M1**：state 文件按 `window_key` 区分，或文档说明限制
4. **M2**：延长 running TTL 或在 `postToolUse` 链路上刷新
5. **M4**：改为仅启动时置前，或「显示面板」时才 `orderFrontRegardless`
6. **M5**：✕ 改为隐藏面板，退出仅保留菜单项
7. ~~**L1**：删除或归档未使用的 monitor 模块~~ → 已完成
8. **L3**：README 补全 `logs` 命令；FEATURES 与 README 互链

### 12.5 新用户检查清单

克隆仓库后按顺序：

```bash
chmod +x run.sh
./run.sh paths          # 确认检测到已安装的工具
./run.sh                # 启动
# 菜单栏 → 安装 Hook
# 重启 Cursor / Claude Code / Codex
# 运行一次 Agent 任务，观察面板状态变化
```

若状态始终绿灯 → 见 [README 常见问题](README.md#状态始终绿灯)。

---

## 附录：环境变量

| 变量 | 用途 |
|------|------|
| `AGENT_LIGHT_CURSOR_USER_DATA_DIR` | Cursor 用户数据 |
| `AGENT_LIGHT_CURSOR_CONFIG_DIR` | `~/.cursor` 等价路径 |
| `AGENT_LIGHT_CURSOR_PROJECTS_DIR` | Cursor projects |
| `AGENT_LIGHT_CODEX_HOME` / `CODEX_HOME` | Codex 根目录 |
| `AGENT_LIGHT_CLAUDE_CONFIG_DIR` / `CLAUDE_CONFIG_DIR` | Claude Code 配置 |
| `AGENT_LIGHT_CODEX_SESSIONS_DIR` | Codex sessions |
| `AGENT_LIGHT_CLAUDE_PROJECTS_DIR` | Claude projects |

Hook 脚本环境变量：`AGENT_LIGHT_TOOL=cursor|claude-code|codex`

---

*文档版本：与 Agent Light 1.0.0 代码同步。*
