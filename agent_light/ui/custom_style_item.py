"""Custom style instance card — GIF/image per state with click-to-focus."""

from __future__ import annotations

import logging
from pathlib import Path

import objc
from AppKit import (
    NSColor,
    NSFont,
    NSImage,
    NSImageScaleProportionallyDown,
    NSImageView,
    NSMakeRect,
    NSTextField,
    NSView,
)

from ..models import LightState, MonitoredInstance
from ..styles import STYLES_ROOT, asset_path, is_animated_file
from .kun_silhouette import GIF_DISPLAY_H, KUN_ITEM_HEIGHT, KUN_ITEM_WIDTH
from .view_utils import ClickPassthroughView, ItemClickTarget, make_instance_click_button

logger = logging.getLogger(__name__)

_image_cache: dict[str, NSImage | None] = {}


def _load_image(path: Path) -> NSImage | None:
    key = str(path)
    if key in _image_cache:
        return _image_cache[key]
    if not path.is_file():
        _image_cache[key] = None
        return None
    img = NSImage.alloc().initWithContentsOfFile_(str(path))
    _image_cache[key] = img
    return img


def invalidate_style_cache(style_id: str | None = None) -> None:
    if style_id is None:
        _image_cache.clear()
        return
    prefix = str(STYLES_ROOT / style_id)
    for key in list(_image_cache):
        if key.startswith(prefix):
            del _image_cache[key]


class CustomStyleItemView(NSView):
    """Show running / waiting / idle assets for one custom style."""

    def initWithInstance_clickTarget_styleId_(self, instance, click_target, style_id):
        self = objc.super(CustomStyleItemView, self).initWithFrame_(
            NSMakeRect(0, 0, KUN_ITEM_WIDTH, KUN_ITEM_HEIGHT)
        )
        if self is None:
            return None
        self._instance = instance
        self._click_target = click_target
        self._style_id = style_id
        self._state = LightState.IDLE

        gif_wrap = ClickPassthroughView.alloc().initWithFrame_(
            NSMakeRect(2, 22, KUN_ITEM_WIDTH - 4, GIF_DISPLAY_H)
        )
        self._gif_view = NSImageView.alloc().initWithFrame_(gif_wrap.bounds())
        self._gif_view.setImageScaling_(NSImageScaleProportionallyDown)
        self._gif_view.setAnimates_(False)
        gif_wrap.addSubview_(self._gif_view)
        self.addSubview_(gif_wrap)

        self._label = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 2, KUN_ITEM_WIDTH, 18))
        self._label.setBezeled_(False)
        self._label.setDrawsBackground_(False)
        self._label.setEditable_(False)
        self._label.setSelectable_(False)
        self._label.setAlignment_(1)
        self._label.setFont_(NSFont.boldSystemFontOfSize_(10))
        self._label.setTextColor_(NSColor.whiteColor())
        label_wrap = ClickPassthroughView.alloc().initWithFrame_(NSMakeRect(0, 2, KUN_ITEM_WIDTH, 18))
        label_wrap.addSubview_(self._label)
        self.addSubview_(label_wrap)

        self._click_btn = make_instance_click_button(self.bounds(), instance, click_target)
        self.addSubview_(self._click_btn)

        self.updateInstance_(instance)
        return self

    def isFlipped(self) -> bool:
        return True

    def _short_label(self, name: str) -> str:
        return name if len(name) <= 16 else name[:15] + "…"

    def _label_for_instance(self, instance: MonitoredInstance) -> str:
        project = instance.extra.get("project") or instance.extra.get("workspace")
        if project:
            return self._short_label(str(project))
        if " · " in instance.display_name:
            return self._short_label(instance.display_name.split(" · ")[-1])
        return self._short_label(instance.display_name)

    def _state_key(self, state: LightState) -> str:
        if state == LightState.RUNNING:
            return "running"
        if state == LightState.WAITING:
            return "waiting"
        return "idle"

    def _show_asset(self, state: LightState) -> None:
        key = self._state_key(state)
        path = asset_path(self._style_id, key)  # type: ignore[arg-type]
        img = _load_image(path)
        if img is None:
            self._gif_view.setAnimates_(False)
            self._gif_view.setImage_(None)
            return
        self._gif_view.setImage_(img)
        animate = is_animated_file(path)
        self._gif_view.setAnimates_(animate)

    def _stop_animation(self) -> None:
        self._gif_view.setAnimates_(False)

    def updateInstance_(self, instance: MonitoredInstance) -> None:
        self._instance = instance
        self._state = instance.state
        self._label.setStringValue_(self._label_for_instance(instance))
        self._click_btn.setRepresentedObject_(instance)
        self._click_btn.setFrame_(self.bounds())
        self.addSubview_(self._click_btn)

        labels = {
            LightState.RUNNING: "运行中",
            LightState.WAITING: "人工确认",
            LightState.IDLE: "结束",
        }
        tip = f"{instance.display_name}\n{labels.get(self._state, '')}\n{instance.state_reason}"
        self.setToolTip_(tip)
        self._click_btn.setToolTip_(tip)
        self._show_asset(self._state)
