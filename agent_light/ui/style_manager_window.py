"""Popup window for managing custom display styles."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

import objc
from AppKit import (
    NSAlert,
    NSAlertStyleWarning,
    NSApplicationActivateIgnoringOtherApps,
    NSApp,
    NSBackingStoreBuffered,
    NSBezelStyleRounded,
    NSButton,
    NSColor,
    NSModalPanelWindowLevel,
    NSFont,
    NSImageView,
    NSMakeRect,
    NSOpenPanel,
    NSScrollView,
    NSTableColumn,
    NSTableView,
    NSTextField,
    NSView,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskTitled,
)
from Foundation import NSIndexSet, NSObject

from ..styles import (
    STATE_KEYS,
    STATE_LABELS,
    CustomStyle,
    create_style,
    delete_style,
    import_state_asset,
    list_styles,
    reload_styles,
    save_style_complete,
    validate_style_draft,
)

logger = logging.getLogger(__name__)

WINDOW_W = 580
WINDOW_H = 580
PREVIEW_W = 80
PREVIEW_H = 44


class FlippedRootView(NSView):
    def isFlipped(self) -> bool:
        return True


class _StyleTableDataSource(NSObject):
    def init(self):
        self = objc.super(_StyleTableDataSource, self).init()
        self._styles: list[CustomStyle] = []
        self._selected: CustomStyle | None = None
        return self

    def reload(self) -> None:
        reload_styles()
        self._styles = list_styles()

    def selectedStyle(self) -> CustomStyle | None:
        return self._selected

    def setSelected_(self, style: CustomStyle | None) -> None:
        self._selected = style

    def numberOfRowsInTableView_(self, table_view) -> int:
        return len(self._styles)

    def tableView_objectValueForTableColumn_row_(self, table_view, column, row: int):
        if row < 0 or row >= len(self._styles):
            return ""
        style = self._styles[row]
        return f"{style.banner_emoji}  {style.name}"

    def styleAtRow_(self, row: int) -> CustomStyle | None:
        if 0 <= row < len(self._styles):
            return self._styles[row]
        return None


class StyleManagerController(NSObject):
    def initWithOnChange_(self, on_change: Callable[[], None] | None):
        self = objc.super(StyleManagerController, self).init()
        if self is None:
            return None
        self._on_change = on_change
        self._window: NSWindow | None = None
        self._table: NSTableView | None = None
        self._data = _StyleTableDataSource.alloc().init()
        self._name_field: NSTextField | None = None
        self._emoji_field: NSTextField | None = None
        self._preview_views: dict[str, NSImageView] = {}
        self._path_labels: dict[str, NSTextField] = {}
        self._pick_buttons: dict[str, NSButton] = {}
        self._save_btn: NSButton | None = None
        self._selected_id: str | None = None
        return self

    def show(self) -> None:
        NSApp().activateIgnoringOtherApps_(True)
        if self._window is None:
            self._build_window()
        self._reload_list()
        row = self._table.selectedRow()
        if row < 0 and self._selected_id:
            row = self._row_for_style_id(self._selected_id)
        if row >= 0:
            self._select_row(row)
        else:
            self._apply_selection(-1)
        self._window.center()
        self._window.orderFrontRegardless()
        self._window.makeKeyAndOrderFront_(None)

    def _build_window(self) -> None:
        rect = NSMakeRect(0, 0, WINDOW_W, WINDOW_H)
        mask = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
        window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, mask, NSBackingStoreBuffered, False
        )
        window.setTitle_("我爱发明 — 风格管理")
        window.setReleasedWhenClosed_(False)
        window.setLevel_(NSModalPanelWindowLevel)
        window.setDelegate_(self)

        content = FlippedRootView.alloc().initWithFrame_(rect)

        y = 12
        title = self._make_label("自定义风格列表（保存前请填写全部必填项）", 16, y, WINDOW_W - 32)
        content.addSubview_(title)
        y += 28

        table_h = 140
        scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(16, y, WINDOW_W - 32, table_h))
        scroll.setHasVerticalScroller_(True)
        scroll.setBorderType_(1)
        table = NSTableView.alloc().initWithFrame_(scroll.contentView().bounds())
        col = NSTableColumn.alloc().initWithIdentifier_("name")
        col.setWidth_(WINDOW_W - 60)
        table.addTableColumn_(col)
        table.setHeaderView_(None)
        table.setDelegate_(self)
        table.setDataSource_(self._data)
        table.setColumnAutoresizingStyle_(5)
        scroll.setDocumentView_(table)
        content.addSubview_(scroll)
        self._table = table
        y += table_h + 10

        content.addSubview_(self._make_button("新增风格", 16, y, 90, 28, "addStyle:"))
        content.addSubview_(self._make_button("删除", 112, y, 70, 28, "deleteStyle:"))
        y += 38

        content.addSubview_(self._make_label("名称 *", 16, y, 60, 22))
        self._name_field = self._make_input(80, y - 2, 220, 26)
        content.addSubview_(self._name_field)

        content.addSubview_(self._make_label("Banner emoji *", 320, y, 110, 22))
        self._emoji_field = self._make_input(430, y - 2, 80, 26)
        self._emoji_field.setStringValue_("🎨")
        content.addSubview_(self._emoji_field)
        y += 36

        content.addSubview_(self._make_label("状态素材 *（自动缩放至 80×88，三项均必填）", 16, y, WINDOW_W - 32, 20))
        y += 26

        for state in STATE_KEYS:
            content.addSubview_(self._make_label(f"{STATE_LABELS[state]} *", 16, y, 80, 22))
            pick = self._make_button("选择文件", 100, y - 2, 88, 26, "pickAsset:")
            pick.setTag_(STATE_KEYS.index(state))
            pick.setEnabled_(False)
            content.addSubview_(pick)
            self._pick_buttons[state] = pick

            path_label = NSTextField.alloc().initWithFrame_(NSMakeRect(196, y, 220, 20))
            path_label.setBezeled_(False)
            path_label.setDrawsBackground_(False)
            path_label.setEditable_(False)
            path_label.setSelectable_(False)
            path_label.setFont_(NSFont.systemFontOfSize_(11))
            path_label.setTextColor_(NSColor.secondaryLabelColor())
            path_label.setStringValue_("未设置")
            content.addSubview_(path_label)
            self._path_labels[state] = path_label

            preview = NSImageView.alloc().initWithFrame_(
                NSMakeRect(WINDOW_W - PREVIEW_W - 20, y - 6, PREVIEW_W, PREVIEW_H)
            )
            preview.setImageScaling_(3)
            content.addSubview_(preview)
            self._preview_views[state] = preview
            y += 50

        self._save_btn = self._make_button("保存风格", 16, y, 100, 30, "saveStyle:")
        self._save_btn.setEnabled_(False)
        content.addSubview_(self._save_btn)

        content.addSubview_(self._make_button("关闭", WINDOW_W - 96, y, 80, 30, "closeWindow:"))

        window.setContentView_(content)
        self._window = window

    def _make_label(self, text: str, x: float, y: float, w: float, h: float = 20) -> NSTextField:
        field = NSTextField.alloc().initWithFrame_(NSMakeRect(x, y, w, h))
        field.setBezeled_(False)
        field.setDrawsBackground_(False)
        field.setEditable_(False)
        field.setSelectable_(False)
        field.setStringValue_(text)
        field.setFont_(NSFont.systemFontOfSize_(12))
        return field

    def _make_input(self, x: float, y: float, w: float, h: float) -> NSTextField:
        field = NSTextField.alloc().initWithFrame_(NSMakeRect(x, y, w, h))
        field.setBezeled_(True)
        field.setEditable_(True)
        field.setEnabled_(True)
        return field

    def _make_button(self, title: str, x: float, y: float, w: float, h: float, action: str) -> NSButton:
        btn = NSButton.alloc().initWithFrame_(NSMakeRect(x, y, w, h))
        btn.setTitle_(title)
        btn.setBezelStyle_(NSBezelStyleRounded)
        btn.setTarget_(self)
        btn.setAction_(action)
        btn.setEnabled_(True)
        return btn

    def _reload_list(self) -> None:
        self._data.reload()
        self._table.reloadData()

    def _row_for_style_id(self, style_id: str) -> int:
        for idx, style in enumerate(self._data._styles):
            if style.id == style_id:
                return idx
        return -1

    def _clear_form_fields(self) -> None:
        self._name_field.setStringValue_("")
        self._emoji_field.setStringValue_("🎨")
        for state in STATE_KEYS:
            self._path_labels[state].setStringValue_("未设置 *")
            self._preview_views[state].setImage_(None)

    def _apply_selection(self, row: int) -> None:
        if row < 0:
            self._selected_id = None
            self._data.setSelected_(None)
            self._set_form_enabled(False)
            return
        style = self._data.styleAtRow_(row)
        if style is None:
            self._apply_selection(-1)
            return
        self._data.setSelected_(style)
        self._selected_id = style.id
        self._name_field.setStringValue_(style.name)
        self._emoji_field.setStringValue_(style.banner_emoji)
        self._set_form_enabled(True)
        self._refresh_previews(style.id)

    def _select_row(self, row: int) -> None:
        if row < 0:
            self._table.deselectAll_(None)
            self._apply_selection(-1)
            return
        self._table.selectRowIndexes_byExtendingSelection_(
            NSIndexSet.indexSetWithIndex_(row), False
        )
        self._apply_selection(row)

    def _set_form_enabled(self, enabled: bool) -> None:
        self._name_field.setEnabled_(enabled)
        self._emoji_field.setEnabled_(enabled)
        if self._save_btn:
            self._save_btn.setEnabled_(enabled)
        for btn in self._pick_buttons.values():
            btn.setEnabled_(enabled)

    def _notify_change(self) -> None:
        if self._on_change:
            self._on_change()

    def _show_error(self, message: str) -> None:
        alert = NSAlert.alloc().init()
        alert.setMessageText_("请完善必填项")
        alert.setInformativeText_(message)
        alert.setAlertStyle_(NSAlertStyleWarning)
        alert.runModal()

    def tableViewSelectionDidChange_(self, notification) -> None:
        self._apply_selection(self._table.selectedRow())

    def addStyle_(self, sender) -> None:
        try:
            create_style("新风格", "🎨")
            self._reload_list()
            row = self._data.numberOfRowsInTableView_(self._table) - 1
            self._select_row(row)
        except ValueError as exc:
            self._show_error(str(exc))
        except Exception:
            logger.exception("Failed to add style")
            self._show_error("新增风格失败，请重试")

    def deleteStyle_(self, sender) -> None:
        if not self._selected_id:
            self._show_error("请先选择一个风格")
            return
        style = self._data.selectedStyle()
        if not style:
            return
        alert = NSAlert.alloc().init()
        alert.setMessageText_(f"删除风格「{style.name}」？")
        alert.addButtonWithTitle_("删除")
        alert.addButtonWithTitle_("取消")
        if alert.runModal() != 1000:
            return
        delete_style(self._selected_id)
        self._reload_list()
        self._select_row(-1)
        self._notify_change()

    def saveStyle_(self, sender) -> None:
        if not self._selected_id:
            self._show_error("请先选择一个风格")
            return
        style_id = self._selected_id
        name = self._name_field.stringValue()
        emoji = self._emoji_field.stringValue()
        try:
            save_style_complete(style_id, name=name, banner_emoji=emoji)
            self._reload_list()
            self._select_row(self._row_for_style_id(style_id))
            self._notify_change()
        except ValueError as exc:
            self._show_error(str(exc))

    def pickAsset_(self, sender) -> None:
        if not self._selected_id:
            self._show_error("请先选择一个风格")
            return
        state = STATE_KEYS[sender.tag()]
        panel = NSOpenPanel.openPanel()
        panel.setCanChooseFiles_(True)
        panel.setCanChooseDirectories_(False)
        panel.setAllowsMultipleSelection_(False)
        panel.setAllowedFileTypes_(["gif", "png", "jpg", "jpeg", "webp", "public.image"])
        panel.setMessage_(f"选择「{STATE_LABELS[state]}」图片或动图（必填）")
        if panel.runModal() != 1:
            return
        urls = panel.URLs()
        if not urls:
            return
        try:
            import_state_asset(self._selected_id, state, Path(str(urls[0].path())))
            from .custom_style_item import invalidate_style_cache

            invalidate_style_cache(self._selected_id)
            self._refresh_previews(self._selected_id)
        except Exception as exc:
            logger.exception("Import asset failed")
            self._show_error(str(exc))

    def _refresh_previews(self, style_id: str) -> None:
        from AppKit import NSImage
        from ..styles import asset_path, is_animated_file

        for state in STATE_KEYS:
            path = asset_path(style_id, state)
            label = self._path_labels[state]
            preview = self._preview_views[state]
            if path.is_file():
                label.setStringValue_(path.name)
                img = NSImage.alloc().initWithContentsOfFile_(str(path))
                preview.setImage_(img)
                preview.setAnimates_(is_animated_file(path))
            else:
                label.setStringValue_("未设置 *")
                preview.setImage_(None)

    def closeWindow_(self, sender) -> None:
        self._dismiss_window()

    def windowWillClose_(self, notification) -> None:
        self._select_row(-1)

    def _dismiss_window(self) -> None:
        if self._window:
            self._select_row(-1)
            self._window.orderOut_(None)


_manager: StyleManagerController | None = None


def show_style_manager(on_change: Callable[[], None] | None = None) -> None:
    global _manager
    if _manager is None:
        _manager = StyleManagerController.alloc().initWithOnChange_(on_change)
    elif on_change:
        _manager._on_change = on_change
    _manager.show()
