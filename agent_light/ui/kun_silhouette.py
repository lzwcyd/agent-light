"""Kun mode — dance GIF when running, done portrait when idle, laugh GIF when waiting."""

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
from .view_utils import ClickPassthroughView, ItemClickTarget, make_instance_click_button

logger = logging.getLogger(__name__)

KUN_ITEM_WIDTH = 84.0
KUN_ITEM_HEIGHT = 112.0
GIF_DISPLAY_H = 88.0

_assets: dict[str, NSImage | None] = {}


def _assets_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "assets"


def _load_asset(name: str) -> NSImage | None:
    if name in _assets and _assets[name] is not None:
        return _assets[name]
    path = _assets_dir() / name
    if not path.exists():
        logger.error("Kun asset missing: %s", path)
        _assets[name] = None
        return None
    img = NSImage.alloc().initWithContentsOfFile_(str(path))
    _assets[name] = img
    return img


class KunSilhouetteItemView(NSView):
    """GIF dancer — dance when running, laugh when waiting, done portrait when idle."""

    def initWithInstance_clickTarget_(self, instance: MonitoredInstance, click_target: ItemClickTarget):
        self = objc.super(KunSilhouetteItemView, self).initWithFrame_(
            NSMakeRect(0, 0, KUN_ITEM_WIDTH, KUN_ITEM_HEIGHT)
        )
        if self is None:
            return None
        self._instance = instance
        self._click_target = click_target
        self._state = LightState.IDLE

        gif_h = GIF_DISPLAY_H
        gif_wrap = ClickPassthroughView.alloc().initWithFrame_(
            NSMakeRect(2, 22, KUN_ITEM_WIDTH - 4, gif_h)
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

        self._click_btn = make_instance_click_button(
            self.bounds(),
            instance,
            click_target,
        )
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
            return self._short_label(project)
        if " · " in instance.display_name:
            return self._short_label(instance.display_name.split(" · ")[-1])
        return self._short_label(instance.display_name)

    def _show_static(self, asset_name: str) -> None:
        img = _load_asset(asset_name)
        if img:
            self._gif_view.setAnimates_(False)
            self._gif_view.setImage_(img)

    def _show_animated(self, asset_name: str) -> None:
        img = _load_asset(asset_name)
        if img:
            self._gif_view.setImage_(img)
            self._gif_view.setAnimates_(True)

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
            LightState.RUNNING: "💃 舞动中",
            LightState.WAITING: "😄 待确认",
            LightState.IDLE: "💗 完成",
        }
        tip = f"{instance.display_name}\n{labels.get(self._state, '')}\n{instance.state_reason}"
        self.setToolTip_(tip)
        self._click_btn.setToolTip_(tip)

        if self._state == LightState.RUNNING:
            self._show_animated("kun.gif")
        elif self._state == LightState.WAITING:
            self._show_animated("kun_waiting.gif")
        else:
            self._stop_animation()
            self._show_static("kun_done.jpg")
