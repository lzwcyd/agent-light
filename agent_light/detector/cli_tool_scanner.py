"""Detect CLI AI tool sessions (Codex, Claude Code, etc.) in iTerm/Terminal."""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass, field

import psutil

from ..models import MonitoredInstance

logger = logging.getLogger(__name__)

SHELL_NAMES = {"zsh", "bash", "fish", "sh", "login"}
TERMINAL_NAMES = {"iterm2", "iterm", "terminal", "warp", "alacritty", "kitty"}

# GUI app processes to exclude when matching native "claude" binary name
DESKTOP_APP_MARKERS = (
    "claude.app",
    "claude helper",
    "claude helper (renderer)",
    "claude helper (gpu)",
)


@dataclass(frozen=True)
class CliToolDef:
    tool_name: str
    label: str
    node_cmd_re: re.Pattern[str]
    native_cmd_re: re.Pattern[str]
    pgrep_pattern: str
    native_process_name: str | None = None  # e.g. "codex", "claude"


CLI_TOOLS: list[CliToolDef] = [
    CliToolDef(
        tool_name="codex",
        label="Codex",
        node_cmd_re=re.compile(
            r"(?:@openai/codex|node_global/bin/codex|/bin/codex(?:\.js)?|npx\s+.*codex)",
            re.IGNORECASE,
        ),
        native_cmd_re=re.compile(
            r"(?:codex-darwin-(?:arm64|x64)"
            r"|codex-aarch64-apple-darwin"
            r"|codex-x86[_-]?64-apple-darwin"
            r"|/Caskroom/codex/"
            r"|/vendor/[^/]+/bin/codex\b"
            r"|\bcodex(?:\.js)?(?:\s|$))",
            re.IGNORECASE,
        ),
        pgrep_pattern="codex",
        native_process_name="codex",
    ),
    CliToolDef(
        tool_name="claude-code",
        label="Claude Code",
        node_cmd_re=re.compile(
            r"(?:@anthropic-ai/claude-code|node_global/bin/claude|claude-code/cli\.js|npx\s+.*claude-code)",
            re.IGNORECASE,
        ),
        native_cmd_re=re.compile(
            r"(?:claude-code-darwin-(?:arm64|x64)"
            r"|claude-aarch64-apple-darwin"
            r"|claude-x86[_-]?64-apple-darwin"
            r"|/Caskroom/claude(?:-code)?/"
            r"|/vendor/[^/]+/bin/claude\b"
            r"|\.local/bin/claude\b"
            r"|\bclaude-code(?:\s|$))",
            re.IGNORECASE,
        ),
        pgrep_pattern="claude",
        native_process_name="claude",
    ),
]


@dataclass
class CliProcess:
    tool: CliToolDef
    pid: int
    ppid: int
    kind: str  # "node" | "native"
    cmdline: str
    cwd: str
    tty: str
    name: str


@dataclass
class CliSession:
    tool: CliToolDef
    session_id: str
    node_pid: int | None
    native_pid: int | None
    shell_pid: int | None
    terminal_pid: int | None
    terminal_name: str
    cwd: str
    tty: str
    cmdline: str
    pids: list[int] = field(default_factory=list)


def _short_title(title: str, max_len: int = 28) -> str:
    title = title.strip() or "CLI"
    return title if len(title) <= max_len else title[: max_len - 1] + "…"


def _safe_cmdline(proc: psutil.Process) -> str:
    try:
        return " ".join(proc.cmdline())
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return ""


def _safe_cwd(proc: psutil.Process) -> str:
    try:
        return proc.cwd() or ""
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return ""


def _safe_tty(proc: psutil.Process) -> str:
    try:
        tty = proc.terminal()
        return tty if tty else ""
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return ""


def _safe_exe(proc: psutil.Process) -> str:
    try:
        return proc.exe() or ""
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return ""


def _name_matches_native(name: str, tool: CliToolDef) -> bool:
    if not tool.native_process_name:
        return False
    base = tool.native_process_name.lower()
    if name == base:
        return True
    # psutil may truncate long process names (e.g. codex-aarch64-ap)
    return name.startswith(f"{base}-") or name.startswith(f"{base}_")


def _is_minimal_native_argv(cmdline: str, tool: CliToolDef) -> bool:
    if not tool.native_process_name:
        return False
    argv = cmdline.strip().split()
    if len(argv) != 1:
        return False
    token = argv[0].rstrip("/").split("/")[-1].lower()
    return token == tool.native_process_name.lower()


def _process_identity(name: str, cmdline: str, exe: str) -> str:
    return f"{name}\n{cmdline}\n{exe}"


def _looks_like_native_cli(name: str, cmdline: str, exe: str) -> bool:
    if any(_name_matches_native(name, tool) for tool in CLI_TOOLS):
        return True
    if cmdline.strip():
        return True
    return bool(exe)


def _is_desktop_claude(name: str, cmd_lower: str, exe_lower: str = "") -> bool:
    if "claude-code" in cmd_lower or "@anthropic-ai/claude-code" in cmd_lower:
        return False
    if "/caskroom/claude" in exe_lower and "claude-code" in exe_lower:
        return False
    if any(m in cmd_lower for m in DESKTOP_APP_MARKERS):
        return True
    if "claude.app" in exe_lower or "/claude.app/" in exe_lower:
        return True
    if name == "claude" and "node_modules" not in cmd_lower and "claude-code" not in cmd_lower:
        if ".app/contents" in cmd_lower or "helper" in cmd_lower:
            return True
    return False


def _classify_process(proc: psutil.Process) -> CliProcess | None:
    try:
        name = proc.name().lower()
        cmdline = _safe_cmdline(proc)
        cmd_lower = cmdline.lower()
        exe = _safe_exe(proc)
        exe_lower = exe.lower()
        identity = _process_identity(name, cmdline, exe)

        if not _looks_like_native_cli(name, cmdline, exe):
            return None

        for tool in CLI_TOOLS:
            is_node = name == "node" and bool(tool.node_cmd_re.search(cmdline))
            is_native = bool(tool.native_cmd_re.search(identity))

            if tool.native_process_name and _name_matches_native(name, tool):
                if tool.tool_name == "claude-code" and _is_desktop_claude(name, cmd_lower, exe_lower):
                    continue
                if _is_minimal_native_argv(cmdline, tool):
                    is_native = True
                elif "node_modules" in cmd_lower or is_native:
                    is_native = True
                elif tool.tool_name == "codex":
                    is_native = True

            if not is_node and not is_native:
                continue

            return CliProcess(
                tool=tool,
                pid=proc.pid,
                ppid=proc.ppid(),
                kind="node" if is_node else "native",
                cmdline=cmdline,
                cwd=_safe_cwd(proc),
                tty=_safe_tty(proc),
                name=name,
            )
        return None
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


def _walk_ancestors(pid: int) -> list[tuple[int, str]]:
    chain: list[tuple[int, str]] = []
    try:
        cur = psutil.Process(pid)
        for _ in range(20):
            chain.append((cur.pid, cur.name().lower()))
            if cur.ppid() in (0, cur.pid):
                break
            cur = psutil.Process(cur.ppid())
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return chain


def _extract_terminal_info(pid: int) -> tuple[int | None, str, int | None]:
    shell_pid = None
    terminal_pid = None
    terminal_name = "Terminal"
    for p, name in _walk_ancestors(pid):
        if name in SHELL_NAMES and shell_pid is None:
            shell_pid = p
        if name in TERMINAL_NAMES:
            terminal_pid = p
            terminal_name = "iTerm" if "iterm" in name else name.capitalize()
            break
    return terminal_pid, terminal_name, shell_pid


def _collect_via_pgrep(tool: CliToolDef, seen: set[int]) -> list[CliProcess]:
    result: list[CliProcess] = []
    try:
        out = subprocess.run(
            ["pgrep", "-lf", tool.pgrep_pattern],
            capture_output=True,
            text=True,
            timeout=3,
        )
        for line in out.stdout.splitlines():
            parts = line.strip().split(" ", 1)
            if len(parts) < 2:
                continue
            pid = int(parts[0])
            if pid in seen:
                continue
            try:
                cp = _classify_process(psutil.Process(pid))
                if cp and cp.tool.tool_name == tool.tool_name:
                    seen.add(pid)
                    result.append(cp)
            except (psutil.NoSuchProcess, ValueError):
                continue
    except (subprocess.SubprocessError, FileNotFoundError) as exc:
        logger.debug("pgrep fallback failed for %s: %s", tool.tool_name, exc)
    return result


def _collect_cli_processes() -> list[CliProcess]:
    found: list[CliProcess] = []
    seen: set[int] = set()

    for proc in psutil.process_iter(["pid"]):
        try:
            cp = _classify_process(psutil.Process(proc.info["pid"]))
            if cp and cp.pid not in seen:
                seen.add(cp.pid)
                found.append(cp)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    for tool in CLI_TOOLS:
        tool_found = [p for p in found if p.tool.tool_name == tool.tool_name]
        if not tool_found:
            found.extend(_collect_via_pgrep(tool, seen))

    logger.debug(
        "CLI processes: %s",
        [(p.tool.tool_name, p.pid, p.kind, p.tty or "no-tty", p.cmdline[:50]) for p in found],
    )
    return found


def _build_sessions_for_tool(processes: list[CliProcess]) -> list[CliSession]:
    if not processes:
        return []

    tool = processes[0].tool
    node_by_pid = {p.pid: p for p in processes if p.kind == "node"}
    native_by_ppid: dict[int, CliProcess] = {}
    for p in processes:
        if p.kind == "native":
            native_by_ppid[p.ppid] = p

    used: set[int] = set()
    sessions: list[CliSession] = []

    for node in node_by_pid.values():
        native = native_by_ppid.get(node.pid)
        if node.pid in used:
            continue
        used.add(node.pid)
        if native:
            used.add(native.pid)

        terminal_pid, terminal_name, shell_pid = _extract_terminal_info(node.pid)
        cwd = node.cwd or (native.cwd if native else "")
        tty = node.tty or (native.tty if native else "")
        pids = [node.pid] + ([native.pid] if native else [])

        sessions.append(
            CliSession(
                tool=tool,
                session_id=f"{tool.tool_name}-node-{node.pid}",
                node_pid=node.pid,
                native_pid=native.pid if native else None,
                shell_pid=shell_pid,
                terminal_pid=terminal_pid,
                terminal_name=terminal_name,
                cwd=cwd,
                tty=tty,
                cmdline=node.cmdline,
                pids=pids,
            )
        )

    for native in (p for p in processes if p.kind == "native"):
        if native.pid in used:
            continue
        used.add(native.pid)
        terminal_pid, terminal_name, shell_pid = _extract_terminal_info(native.pid)
        sessions.append(
            CliSession(
                tool=tool,
                session_id=f"{tool.tool_name}-native-{native.pid}",
                node_pid=None,
                native_pid=native.pid,
                shell_pid=shell_pid,
                terminal_pid=terminal_pid,
                terminal_name=terminal_name,
                cwd=native.cwd,
                tty=native.tty,
                cmdline=native.cmdline,
                pids=[native.pid],
            )
        )

    by_tty: dict[str, CliSession] = {}
    no_tty: list[CliSession] = []
    for s in sessions:
        if s.tty:
            key = f"{s.tool.tool_name}:{s.tty}"
            prev = by_tty.get(key)
            if prev is None or len(s.pids) > len(prev.pids):
                by_tty[key] = s
        else:
            no_tty.append(s)

    return list(by_tty.values()) + no_tty


def _session_to_instance(s: CliSession) -> MonitoredInstance:
    folder = s.cwd.rstrip("/").split("/")[-1] if s.cwd else "CLI"
    if s.terminal_name == "iTerm":
        display = f"{s.tool.label} · iTerm · {_short_title(folder)}"
    else:
        display = f"{s.tool.label} · {_short_title(folder)}"

    monitor_pid = s.native_pid or s.node_pid or (s.pids[0] if s.pids else 0)

    return MonitoredInstance(
        instance_id=s.session_id,
        tool_name=s.tool.tool_name,
        display_name=display,
        pid=monitor_pid,
        extra={
            "cwd": s.cwd,
            "cmdline": s.cmdline,
            "node_pid": s.node_pid,
            "native_pid": s.native_pid,
            "shell_pid": s.shell_pid,
            "terminal_pid": s.terminal_pid,
            "terminal_name": s.terminal_name,
            "tty": s.tty,
            "monitor_pids": s.pids,
        },
    )


def scan_cli_instances() -> list[MonitoredInstance]:
    """Scan all configured CLI tools (Codex, Claude Code, …)."""
    processes = _collect_cli_processes()
    by_tool: dict[str, list[CliProcess]] = {}
    for p in processes:
        by_tool.setdefault(p.tool.tool_name, []).append(p)

    instances: list[MonitoredInstance] = []
    for tool_name, procs in by_tool.items():
        sessions = _build_sessions_for_tool(procs)
        logger.info(
            "%s sessions: %d → %s",
            tool_name,
            len(sessions),
            [
                f"{s.terminal_name}/{s.tty or s.node_pid} "
                f"cwd={s.cwd.split('/')[-1] if s.cwd else '?'}"
                for s in sessions
            ],
        )
        for s in sessions:
            if s.pids:
                instances.append(_session_to_instance(s))

    return instances
