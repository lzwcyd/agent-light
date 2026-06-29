"""Shared NSView helpers for the floating panel."""

from __future__ import annotations

import logging
from typing import Callable

import objc
from AppKit import NSButton, NSMomentaryChangeButton, NSView
from Foundation import NSObject

from ..models import MonitoredInstance

logger = logging.getLogger(__name__)

# NSBezelStyleShadowlessSquare
_BEZEL_SHADOWLESS = 12


class ClickPassthroughView(NSView):
    """Ignore mouse hits so the parent item view receives clicks."""

    def hitTest_(self, point):
        return None

    def acceptsFirstMouse_(self, event):
        return True


class ItemClickTarget(NSObject):
    """NSObject bridge for transparent instance click buttons."""

    def initWithCallback_(self, callback: Callable[[MonitoredInstance], None]):
        self = objc.super(ItemClickTarget, self).init()
        if self is None:
            return None
        self._callback = callback
        return self

    def clicked_(self, sender) -> None:
        instance = sender.representedObject()
        if instance is not None and self._callback:
            logger.info("Instance click button: %s", instance.display_name)
            self._callback(instance)


def make_instance_click_button(
    frame,
    instance: MonitoredInstance,
    target: ItemClickTarget,
) -> NSButton:
    btn = NSButton.alloc().initWithFrame_(frame)
    btn.setButtonType_(NSMomentaryChangeButton)
    btn.setBezelStyle_(_BEZEL_SHADOWLESS)
    btn.setBordered_(False)
    btn.setTitle_("")
    btn.setTransparent_(True)
    btn.setRepresentedObject_(instance)
    btn.setTarget_(target)
    btn.setAction_("clicked:")
    return btn
