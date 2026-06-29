"""Agent Light - main entry point."""

from __future__ import annotations

import argparse
import logging

from AppKit import (
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSApp,
    NSMenu,
    NSMenuItem,
    NSStatusBar,
    NSVariableStatusItemLength,
    NSTimer,
    NSRunLoop,
    NSDefaultRunLoopMode,
)
from Foundation import NSObject

from .detector import analyze_states, scan_instances
from .models import LightState
from .tool_paths import get_resolved_tool_paths
from .constants import APP_DATA_DIR, APP_LOGGER_NAME
from .logging_config import is_quiet_mode, setup_logging
from .shutdown import (
    consume_shutdown_flag,
    install_signal_handlers,
    register_delegate_getter,
    register_shutdown,
    remove_pid,
    write_pid,
)
from .settings import (
    get_display_mode,
    get_hide_idle,
    get_hooks_reminder_dismissed,
    set_display_mode,
    set_hide_idle,
    set_hooks_reminder_dismissed,
)
from .styles import get_style, list_complete_styles, reload_styles
from .ui.style_manager_window import show_style_manager
from .ui.traffic_light_panel import TrafficLightPanel

logger = logging.getLogger(APP_LOGGER_NAME)

POLL_INTERVAL = 1.5


class AppDelegate(NSObject):
    def applicationDidFinishLaunching_(self, notification) -> None:
        self._panel_manager = TrafficLightPanel(on_close=lambda: self.performShutdown_("panel-close"))
        self._panel = self._panel_manager.setup()
        self._style_menu_items: list = []
        self._setup_status_bar()
        self._panel.makeKeyAndOrderFront_(None)
        self._panel.orderFrontRegardless()

        write_pid()
        register_shutdown(lambda reason: self.performShutdown_(reason))

        self.tick_(None)
        self._timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            POLL_INTERVAL, self, "tick:", None, True
        )
        NSRunLoop.currentRunLoop().addTimer_forMode_(self._timer, NSDefaultRunLoopMode)
        logger.info("Agent Light started successfully")
        self._maybe_show_hooks_reminder()

    def _setup_status_bar(self) -> None:
        self._status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
        self._status_item.setToolTip_("Agent Light — AI 工具监控")
        self._rebuild_menu()
        self._update_status_icon()
        logger.info("Status bar menu created")

    def _rebuild_menu(self) -> None:
        reload_styles()
        menu = NSMenu.alloc().init()

        show_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("显示面板", "showPanel:", "")
        show_item.setTarget_(self)
        menu.addItem_(show_item)
        menu.addItem_(NSMenuItem.separatorItem())

        mode = get_display_mode()

        traffic = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("🚦 交通灯", "selectTrafficMode:", "")
        traffic.setTarget_(self)
        traffic.setState_(1 if mode == "traffic" else 0)
        menu.addItem_(traffic)
        self._traffic_menu_item = traffic

        kun = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("我爱坤坤💗💗", "selectKunMode:", "")
        kun.setTarget_(self)
        kun.setState_(1 if mode == "kun" else 0)
        menu.addItem_(kun)
        self._kun_menu_item = kun

        self._style_menu_items = []
        styles = list_complete_styles()
        if styles:
            menu.addItem_(NSMenuItem.separatorItem())
        for style in styles:
            title = f"{style.banner_emoji} {style.name}"
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, "selectCustomStyle:", "")
            item.setTarget_(self)
            item.setRepresentedObject_(style.id)
            item.setState_(1 if mode == f"custom:{style.id}" else 0)
            menu.addItem_(item)
            self._style_menu_items.append(item)

        menu.addItem_(NSMenuItem.separatorItem())
        hide_idle = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("仅显示活动", "toggleHideIdle:", "")
        hide_idle.setTarget_(self)
        hide_idle.setState_(1 if get_hide_idle() else 0)
        menu.addItem_(hide_idle)

        menu.addItem_(NSMenuItem.separatorItem())
        invent = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("我爱发明", "openStyleManager:", "")
        invent.setTarget_(self)
        menu.addItem_(invent)

        menu.addItem_(NSMenuItem.separatorItem())
        install_hooks = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("安装 Hook", "installHooks:", "")
        install_hooks.setTarget_(self)
        menu.addItem_(install_hooks)
        self._install_hooks_menu_item = install_hooks

        uninstall_hooks = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("删除 Hook", "uninstallHooks:", "")
        uninstall_hooks.setTarget_(self)
        menu.addItem_(uninstall_hooks)

        menu.addItem_(NSMenuItem.separatorItem())
        about_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("关于", "showAbout:", "")
        about_item.setTarget_(self)
        menu.addItem_(about_item)

        if not is_quiet_mode():
            log_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("打开日志", "openLogs:", "")
            log_item.setTarget_(self)
            menu.addItem_(log_item)

        menu.addItem_(NSMenuItem.separatorItem())
        quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("退出 Agent Light", "quitApp:", "q")
        quit_item.setTarget_(self)
        menu.addItem_(quit_item)

        self._status_item.setMenu_(menu)
        self._update_hooks_menu_titles()

    def _update_hooks_menu_titles(self) -> None:
        from .agent_hooks import hooks_install_status
        from .tool_presence import get_available_tools

        available = get_available_tools()
        if not available:
            if hasattr(self, "_install_hooks_menu_item") and self._install_hooks_menu_item:
                self._install_hooks_menu_item.setTitle_("安装 Hook（未检测到工具）")
            return

        status = hooks_install_status()
        installed = sum(1 for tool in available if status.get(tool))
        total = len(available)
        if hasattr(self, "_install_hooks_menu_item") and self._install_hooks_menu_item:
            suffix = f" ({installed}/{total})" if installed < total else " ✓"
            self._install_hooks_menu_item.setTitle_(f"安装 Hook{suffix}")

    def _show_hook_alert(self, title: str, message: str, informative: str) -> None:
        from AppKit import NSAlert, NSAlertStyleInformational

        alert = NSAlert.alloc().init()
        alert.setMessageText_(message)
        alert.setInformativeText_(informative)
        alert.setAlertStyle_(NSAlertStyleInformational)
        alert.addButtonWithTitle_("确定")
        alert.runModal()
        logger.info("%s: %s", title, informative.replace("\n", " | "))

    def _maybe_show_hooks_reminder(self) -> None:
        from .agent_hooks import hooks_need_install
        from .tool_presence import (
            format_available_tools_summary,
            format_missing_tools_summary,
            get_available_tools,
        )

        if get_hooks_reminder_dismissed() or not hooks_need_install():
            return

        available = get_available_tools()
        if not available:
            return

        from AppKit import NSAlert, NSAlertFirstButtonReturn, NSAlertSecondButtonReturn, NSAlertThirdButtonReturn

        missing = format_missing_tools_summary()
        alert = NSAlert.alloc().init()
        alert.setMessageText_("尚未安装 Agent Hook")
        alert.setInformativeText_(
            f"{format_available_tools_summary()}\n"
            f"{missing}\n\n"
            "未安装 Hook 时无法检测已安装工具的运行状态。\n"
            "安装时会自动检测配置目录，并合并写入，不会覆盖你已有的 Hook 配置。\n\n"
            "可从菜单栏选择「安装 Hook」随时安装。"
        )
        alert.addButtonWithTitle_("立即安装")
        alert.addButtonWithTitle_("稍后提醒")
        alert.addButtonWithTitle_("不再提醒")
        choice = alert.runModal()
        if choice == NSAlertFirstButtonReturn:
            self.installHooks_(None)
        elif choice == NSAlertThirdButtonReturn:
            set_hooks_reminder_dismissed(True)

    def installHooks_(self, sender) -> None:
        import sys

        from .agent_hooks import format_hook_results, install_all_hooks_detailed
        from .tool_presence import format_available_tools_summary, get_available_tools

        if not get_available_tools():
            from AppKit import NSAlert, NSAlertStyleInformational

            alert = NSAlert.alloc().init()
            alert.setMessageText_("未检测到 AI 工具")
            alert.setInformativeText_(
                "本机未发现 Cursor、Claude Code 或 Codex。\n\n"
                f"请先安装并至少运行一次对应工具，或在 {APP_DATA_DIR / 'settings.json'} 中配置 tool_paths。"
            )
            alert.setAlertStyle_(NSAlertStyleInformational)
            alert.runModal()
            return

        results = install_all_hooks_detailed(sys.executable)
        self._update_hooks_menu_titles()
        failed = [r for r in results if not r.ok and not r.skipped]
        changed = [r for r in results if r.ok and not r.skipped]
        summary = format_available_tools_summary() + "\n\n" + format_hook_results(results)
        if failed:
            from AppKit import NSAlert, NSAlertStyleWarning

            alert = NSAlert.alloc().init()
            alert.setMessageText_("Hook 安装未全部成功")
            alert.setInformativeText_(summary + "\n\n请重启对应 AI 工具后生效。")
            alert.setAlertStyle_(NSAlertStyleWarning)
            alert.runModal()
        elif changed:
            self._show_hook_alert(
                "install-hooks",
                "Hook 安装完成",
                summary + "\n\n请重启本次变更涉及的工具后生效。",
            )
        else:
            self._show_hook_alert(
                "install-hooks",
                "Hook 已是最新",
                summary + "\n\n已检测到的工具 Hook 均完整，无需变更。",
            )
        if not failed:
            set_hooks_reminder_dismissed(True)

    def uninstallHooks_(self, sender) -> None:
        from AppKit import NSAlert, NSAlertFirstButtonReturn, NSAlertStyleInformational, NSAlertStyleWarning
        from .agent_hooks import format_hook_results, get_installed_hook_tools, uninstall_all_hooks
        from .tool_presence import TOOL_LABELS

        installed = get_installed_hook_tools()
        if not installed:
            alert = NSAlert.alloc().init()
            alert.setMessageText_("没有可删除的 Hook")
            alert.setInformativeText_("当前未发现已安装的 Agent Light Hook。")
            alert.setAlertStyle_(NSAlertStyleInformational)
            alert.runModal()
            return

        tool_names = "、".join(TOOL_LABELS.get(t, t) for t in installed)
        alert = NSAlert.alloc().init()
        alert.setMessageText_("删除 Agent Light Hook？")
        alert.setInformativeText_(
            f"将移除以下工具的 Agent Light Hook：{tool_names}\n\n"
            "只会删除 Agent Light 添加的脚本和配置项，不会修改你原有的其他 Hook。"
        )
        alert.setAlertStyle_(NSAlertStyleWarning)
        alert.addButtonWithTitle_("删除")
        alert.addButtonWithTitle_("取消")
        if alert.runModal() != NSAlertFirstButtonReturn:
            return

        results = uninstall_all_hooks()
        self._update_hooks_menu_titles()
        failed = [r for r in results if not r.ok and not r.skipped]
        if failed:
            alert = NSAlert.alloc().init()
            alert.setMessageText_("Hook 删除未全部成功")
            alert.setInformativeText_(format_hook_results(results))
            alert.setAlertStyle_(NSAlertStyleWarning)
            alert.runModal()
        else:
            self._show_hook_alert(
                "uninstall-hooks",
                "Hook 已删除",
                format_hook_results(results) + "\n\n请重启对应 AI 工具后生效。",
            )

    def _apply_display_mode(self, mode: str) -> None:
        if mode.startswith("custom:"):
            style_id = mode.split(":", 1)[1]
            from .styles import is_style_complete

            if not is_style_complete(style_id):
                from AppKit import NSAlert, NSAlertStyleWarning

                alert = NSAlert.alloc().init()
                alert.setMessageText_("风格未完成")
                alert.setInformativeText_("请先在「我爱发明」中填写全部必填项并保存。")
                alert.setAlertStyle_(NSAlertStyleWarning)
                alert.runModal()
                return
        set_display_mode(mode)
        self._panel_manager.set_display_mode(mode)
        self._rebuild_menu()
        self._update_status_icon()
        self._panel.orderFrontRegardless()
        if self._panel_manager._last_instances:
            self._panel_manager.update(self._panel_manager._last_instances)
        logger.info("Display mode → %s", mode)

    def _update_status_icon(self) -> None:
        btn = self._status_item.button()
        if not btn:
            return
        mode = get_display_mode()
        if mode == "kun":
            btn.setTitle_("💗")
        elif mode == "traffic":
            btn.setTitle_("🚦")
        elif mode.startswith("custom:"):
            style = get_style(mode.split(":", 1)[1])
            btn.setTitle_(style.banner_emoji if style else "🎨")
        else:
            btn.setTitle_("🚦")

    def selectTrafficMode_(self, sender) -> None:
        self._apply_display_mode("traffic")

    def selectKunMode_(self, sender) -> None:
        self._apply_display_mode("kun")

    def selectCustomStyle_(self, sender) -> None:
        style_id = sender.representedObject()
        if style_id:
            self._apply_display_mode(f"custom:{style_id}")

    def toggleHideIdle_(self, sender) -> None:
        set_hide_idle(not get_hide_idle())
        self._rebuild_menu()   # 刷新勾选态
        self.tick_(None)       # 立即按新设置重渲染面板

    def openStyleManager_(self, sender) -> None:
        show_style_manager(on_change=self._on_styles_changed)

    def _on_styles_changed(self) -> None:
        mode = get_display_mode()
        if mode.startswith("custom:"):
            style_id = mode.split(":", 1)[1]
            if get_style(style_id) is None:
                self._apply_display_mode("traffic")
                return
        self._rebuild_menu()
        self._update_status_icon()
        if self._panel_manager._last_instances:
            self._panel_manager.update(self._panel_manager._last_instances)

    def showPanel_(self, sender) -> None:
        self._panel.orderFrontRegardless()
        logger.info("Panel shown via status bar")

    def showAbout_(self, sender) -> None:
        from AppKit import NSAlert
        from .logging_config import LOG_FILE

        log_line = "静默模式（无日志）" if is_quiet_mode() else f"日志：{LOG_FILE}"
        alert = NSAlert.alloc().init()
        alert.setMessageText_("Agent Light")
        alert.setInformativeText_(
            "AI 工具交通信号灯监控\n\n"
            "🔴 运行中  🟡 人工确认  🟢 结束\n\n"
            "菜单栏可切换交通灯 / 坤坤 / 自定义风格\n"
            "「我爱发明」管理自定义图片与动图\n\n"
            f"{log_line}"
        )
        alert.runModal()

    def openLogs_(self, sender) -> None:
        from AppKit import NSWorkspace
        from .logging_config import LOG_DIR
        NSWorkspace.sharedWorkspace().openFile_(str(LOG_DIR))
        logger.info("Opened log directory")

    def quitApp_(self, sender) -> None:
        self.performShutdown_("menu-quit")

    def performShutdown_(self, reason) -> None:
        logger.info("Shutting down (%s)", reason)
        if hasattr(self, "_timer") and self._timer:
            self._timer.invalidate()
        if hasattr(self, "_status_item") and self._status_item:
            NSStatusBar.systemStatusBar().removeStatusItem_(self._status_item)
        remove_pid()
        NSApp().terminate_(None)

    def tick_(self, timer) -> None:
        try:
            if consume_shutdown_flag():
                self.performShutdown_("stop-flag")
                return
            instances = scan_instances()
            logger.debug("Scanned %d instance(s)", len(instances))
            instances = analyze_states(instances)
            if get_hide_idle():
                instances = [i for i in instances if i.state != LightState.IDLE]
            self._panel_manager.update(instances)
        except Exception:
            logger.exception("Poll tick failed")

    def applicationShouldTerminateAfterLastWindowClosed_(self, app) -> bool:
        return False

    def applicationWillTerminate_(self, notification) -> None:
        remove_pid()
        logger.info("Application terminated")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Agent Light — AI 工具交通信号灯监控")
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help=f"启用日志：写入 {APP_DATA_DIR / 'logs'} 并输出到控制台",
    )
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    return parser.parse_args()


def main() -> None:
    import os

    # 冻结的 .app 同时充当 Agent Hook relay：hook 脚本以 AGENT_LIGHT_RELAY=1
    # 调用本可执行文件，读 stdin 处理一次事件后退出，绝不初始化 GUI。
    # 必须早于 parse_args()——上游工具可能向 argv 注入自己的参数。
    if os.environ.get("AGENT_LIGHT_RELAY") == "1":
        from .agent_hooks.relay import run_relay

        raise SystemExit(run_relay())

    args = parse_args()
    quiet = not args.verbose if not args.quiet else True
    setup_logging(quiet=quiet)
    install_signal_handlers()
    if not quiet:
        paths = get_resolved_tool_paths()
        logger.info("Tool paths resolved:")
        for key, value in paths.items():
            logger.info("  %s → %s", key, value)

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    delegate = AppDelegate.alloc().init()
    app.setDelegate_(delegate)
    register_delegate_getter(lambda: delegate)
    app.run()


if __name__ == "__main__":
    main()
