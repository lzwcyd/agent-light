"""Agent hooks integration for Cursor, Claude Code, and Codex."""

__all__ = [
    "format_hook_results",
    "get_installed_hook_tools",
    "hooks_install_status",
    "hooks_need_install",
    "install_all_hooks",
    "install_all_hooks_detailed",
    "install_claude_hooks",
    "install_codex_hooks",
    "install_cursor_hooks",
    "is_all_hooks_installed",
    "is_claude_hooks_installed",
    "is_codex_hooks_installed",
    "is_cursor_hooks_installed",
    "is_cli_hooks_installed",
    "uninstall_all_hooks",
    "uninstall_claude_hooks",
    "uninstall_codex_hooks",
    "uninstall_cursor_hooks",
]


def install_all_hooks(*args, **kwargs):
    from .install import install_all_hooks as _install

    return _install(*args, **kwargs)


def install_all_hooks_detailed(*args, **kwargs):
    from .install import install_all_hooks_detailed as _install

    return _install(*args, **kwargs)


def install_cursor_hooks(*args, **kwargs):
    from .install import install_cursor_hooks as _install

    return _install(*args, **kwargs)


def install_claude_hooks(*args, **kwargs):
    from .install import install_claude_hooks as _install

    return _install(*args, **kwargs)


def install_codex_hooks(*args, **kwargs):
    from .install import install_codex_hooks as _install

    return _install(*args, **kwargs)


def uninstall_all_hooks(*args, **kwargs):
    from .install import uninstall_all_hooks as _fn

    return _fn(*args, **kwargs)


def uninstall_cursor_hooks(*args, **kwargs):
    from .install import uninstall_cursor_hooks as _fn

    return _fn(*args, **kwargs)


def uninstall_claude_hooks(*args, **kwargs):
    from .install import uninstall_claude_hooks as _fn

    return _fn(*args, **kwargs)


def uninstall_codex_hooks(*args, **kwargs):
    from .install import uninstall_codex_hooks as _fn

    return _fn(*args, **kwargs)


def is_cursor_hooks_installed():
    from .install import is_cursor_hooks_installed as _check

    return _check()


def is_claude_hooks_installed():
    from .install import is_claude_hooks_installed as _check

    return _check()


def is_codex_hooks_installed():
    from .install import is_codex_hooks_installed as _check

    return _check()


def is_cli_hooks_installed(tool_name: str):
    from .install import is_cli_hooks_installed as _check

    return _check(tool_name)


def is_all_hooks_installed():
    from .install import is_all_hooks_installed as _check

    return _check()


def hooks_install_status():
    from .install import hooks_install_status as _status

    return _status()


def get_installed_hook_tools(*args, **kwargs):
    from .install import get_installed_hook_tools as _fn

    return _fn(*args, **kwargs)


def hooks_need_install():
    from .install import hooks_need_install as _check

    return _check()


def format_hook_results(results):
    from .install import format_hook_results as _format

    return _format(results)
