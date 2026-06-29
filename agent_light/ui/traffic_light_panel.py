"""Traffic light floating panel UI."""

from __future__ import annotations

import logging
from typing import Callable

import objc
from AppKit import (
    NSBackingStoreBuffered,
    NSBezelStyleSmallSquare,
    NSButton,
    NSColor,
    NSFont,
    NSFloatingWindowLevel,
    NSMakeRect,
    NSMomentaryChangeButton,
    NSPanel,
    NSScreen,
    NSTextField,
    NSView,
    NSWindowStyleMaskBorderless,
    NSWindowStyleMaskNonactivatingPanel,
    NSWindowStyleMaskUtilityWindow,
)
from Foundation import NSMakeSize, NSZeroRect, NSObject

from ..focus import focus_instance
from ..models import LightState, MonitoredInstance
from ..settings import get_display_mode
from .custom_style_item import CustomStyleItemView
from .kun_silhouette import KUN_ITEM_HEIGHT, KUN_ITEM_WIDTH, KunSilhouetteItemView
from .view_utils import ClickPassthroughView, ItemClickTarget, make_instance_click_button

logger = logging.getLogger(__name__)

# Layout
LIGHT_SIZE = 24.0
LIGHT_GAP = 7.0
ITEM_WIDTH = 84.0
ITEM_HEIGHT = 112.0
ITEM_GAP = 12.0
PANEL_PAD_H = 14.0
PANEL_PAD_V = 10.0
CLOSE_BTN = 18.0

# Light colors — on: vivid; off: dim but still visible
COLORS = {
    LightState.RUNNING: (
        NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 0.18, 0.15, 1.0),
        NSColor.colorWithCalibratedRed_green_blue_alpha_(0.55, 0.14, 0.12, 1.0),
    ),
    LightState.WAITING: (
        NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 0.82, 0.0, 1.0),
        NSColor.colorWithCalibratedRed_green_blue_alpha_(0.55, 0.42, 0.0, 1.0),
    ),
    LightState.IDLE: (
        NSColor.colorWithCalibratedRed_green_blue_alpha_(0.15, 0.90, 0.38, 1.0),
        NSColor.colorWithCalibratedRed_green_blue_alpha_(0.12, 0.48, 0.22, 1.0),
    ),
}

PANEL_BG = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.13, 0.14, 0.16, 0.94)
HOUSING_BG = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.08, 0.08, 0.10, 1.0)


class PanelRootView(NSView):
    """Root content view — keeps the close button above instance items."""

    def initWithContainer_closeButton_(self, container, close_button):
        self = objc.super(PanelRootView, self).initWithFrame_(NSZeroRect)
        if self is None:
            return None
        self._container = container
        self._close_button = close_button
        self.addSubview_(container)
        self.addSubview_(close_button)
        return self

    def isFlipped(self) -> bool:
        return True

    def resizeSubviewsWithOldSize_(self, old_size) -> None:
        bounds = self.bounds()
        self._container.setFrame_(bounds)
        width = bounds.size.width
        self._close_button.setFrame_(
            NSMakeRect(width - CLOSE_BTN - 6, 4, CLOSE_BTN, CLOSE_BTN)
        )
        self.addSubview_(self._close_button)

    def acceptsFirstMouse_(self, event):
        return True


def _set_layer_bg(view: NSView, color: NSColor, corner: float = 0) -> None:
    view.setWantsLayer_(True)
    layer = view.layer()
    layer.setBackgroundColor_(color.CGColor())
    if corner > 0:
        layer.setCornerRadius_(corner)


class LightDotView(ClickPassthroughView):
    """Single colored dot using CALayer — reliable on macOS."""

    def initWithFrame_(self, frame):
        self = objc.super(LightDotView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.setWantsLayer_(True)
        self._on = False
        self._on_color = NSColor.grayColor()
        self._off_color = NSColor.darkGrayColor()
        return self

    def setup_colors(self, on_color, off_color) -> None:
        self._on_color = on_color
        self._off_color = off_color
        self._apply()

    def setOn_(self, on: bool) -> None:
        self._on = on
        self._apply()

    def _apply(self) -> None:
        color = self._on_color if self._on else self._off_color
        layer = self.layer()
        layer.setBackgroundColor_(color.CGColor())
        layer.setCornerRadius_(self.frame().size.width / 2)
        if self._on:
            layer.setBorderWidth_(1.5)
            layer.setBorderColor_(NSColor.colorWithWhite_alpha_(1.0, 0.45).CGColor())
            layer.setShadowOpacity_(1.0)
            layer.setShadowRadius_(10)
            layer.setShadowOffset_((0, -2))
            layer.setShadowColor_(color.CGColor())
        else:
            layer.setBorderWidth_(0.5)
            layer.setBorderColor_(NSColor.colorWithWhite_alpha_(0.2, 0.35).CGColor())
            layer.setShadowOpacity_(0)


class TrafficLightItemView(NSView):
    """One traffic-light unit: 3 dots + label."""

    def initWithInstance_clickTarget_(self, instance: MonitoredInstance, click_target: ItemClickTarget):
        self = objc.super(TrafficLightItemView, self).initWithFrame_(
            NSMakeRect(0, 0, ITEM_WIDTH, ITEM_HEIGHT)
        )
        if self is None:
            return None
        self._instance = instance
        self._click_target = click_target
        self._dots: dict[LightState, LightDotView] = {}

        # Housing background
        housing_h = LIGHT_SIZE * 3 + LIGHT_GAP * 2 + 16
        self._housing = ClickPassthroughView.alloc().initWithFrame_(
            NSMakeRect(4, 22, ITEM_WIDTH - 8, housing_h)
        )
        _set_layer_bg(self._housing, HOUSING_BG, corner=12)
        self.addSubview_(self._housing)

        order = [LightState.RUNNING, LightState.WAITING, LightState.IDLE]
        y = housing_h - LIGHT_SIZE - 8
        for state in order:
            on_c, off_c = COLORS[state]
            dot = LightDotView.alloc().initWithFrame_(
                NSMakeRect((ITEM_WIDTH - 8 - LIGHT_SIZE) / 2, y, LIGHT_SIZE, LIGHT_SIZE)
            )
            dot.setup_colors(on_c, off_c)
            self._housing.addSubview_(dot)
            self._dots[state] = dot
            y -= LIGHT_SIZE + LIGHT_GAP

        self._label = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 2, ITEM_WIDTH, 18))
        self._label.setBezeled_(False)
        self._label.setDrawsBackground_(False)
        self._label.setEditable_(False)
        self._label.setSelectable_(False)
        self._label.setAlignment_(1)
        self._label.setFont_(NSFont.boldSystemFontOfSize_(10))
        self._label.setTextColor_(NSColor.whiteColor())
        passthrough_label = ClickPassthroughView.alloc().initWithFrame_(NSMakeRect(0, 2, ITEM_WIDTH, 18))
        passthrough_label.addSubview_(self._label)
        self.addSubview_(passthrough_label)

        self._click_btn = make_instance_click_button(
            self.bounds(),
            instance,
            click_target,
        )
        self.addSubview_(self._click_btn)

        self.updateInstance_(instance)
        logger.debug("Created traffic light item: %s", instance.display_name)
        return self

    def _short_label(self, name: str) -> str:
        if len(name) > 16:
            return name[:15] + "…"
        return name

    def _label_for_instance(self, instance: MonitoredInstance) -> str:
        """Show project name under the light; full name stays in tooltip."""
        project = instance.extra.get("project") or instance.extra.get("workspace")
        if project:
            return self._short_label(project)
        if " · " in instance.display_name:
            return self._short_label(instance.display_name.split(" · ")[-1])
        return self._short_label(instance.display_name)

    def updateInstance_(self, instance: MonitoredInstance) -> None:
        self._instance = instance
        active = instance.state
        for state, dot in self._dots.items():
            dot.setOn_(state == active)

        name = self._label_for_instance(instance)
        self._label.setStringValue_(name)
        self._click_btn.setRepresentedObject_(instance)
        self._click_btn.setFrame_(self.bounds())
        self.addSubview_(self._click_btn)

        labels = {
            LightState.RUNNING: "🔴 工作中",
            LightState.WAITING: "🟡 待确认",
            LightState.IDLE: "🟢 空闲",
        }
        tip = f"{instance.display_name}\n{labels.get(active, '')}\n{instance.state_reason}"
        self.setToolTip_(tip)
        self._click_btn.setToolTip_(tip)

    def isFlipped(self) -> bool:
        return True


class TrafficLightContainerView(NSView):
    def initWithClickTarget_displayMode_(self, click_target: ItemClickTarget, display_mode: str):
        self = objc.super(TrafficLightContainerView, self).initWithFrame_(NSZeroRect)
        if self is None:
            return None
        self._click_target = click_target
        self._display_mode = display_mode
        self._items: dict[str, NSView] = {}
        self._instances: list[MonitoredInstance] = []
        self._empty_label: NSTextField | None = None
        return self

    def setDisplayMode_(self, display_mode: str) -> None:
        if self._display_mode == display_mode:
            return
        self._display_mode = display_mode
        for item in self._items.values():
            if hasattr(item, "_stop_animation"):
                item._stop_animation()
            item.removeFromSuperview()
        self._items = {}
        if self._instances:
            self.updateInstances_(self._instances)

    def _is_image_mode(self) -> bool:
        return self._display_mode == "kun" or self._display_mode.startswith("custom:")

    def _custom_style_id(self) -> str | None:
        if self._display_mode.startswith("custom:"):
            return self._display_mode.split(":", 1)[1]
        return None

    def _item_size(self) -> tuple[float, float]:
        if self._is_image_mode():
            return KUN_ITEM_WIDTH, KUN_ITEM_HEIGHT
        return ITEM_WIDTH, ITEM_HEIGHT

    def _make_item(self, inst: MonitoredInstance):
        if self._display_mode == "kun":
            return KunSilhouetteItemView.alloc().initWithInstance_clickTarget_(inst, self._click_target)
        style_id = self._custom_style_id()
        if style_id:
            return CustomStyleItemView.alloc().initWithInstance_clickTarget_styleId_(
                inst, self._click_target, style_id
            )
        return TrafficLightItemView.alloc().initWithInstance_clickTarget_(inst, self._click_target)

    def isFlipped(self) -> bool:
        return True

    def updateInstances_(self, instances: list[MonitoredInstance]) -> None:
        self._instances = instances
        current_ids = {i.instance_id for i in instances}

        for iid in list(self._items.keys()):
            if iid not in current_ids:
                item = self._items[iid]
                if hasattr(item, "_stop_animation"):
                    item._stop_animation()
                item.removeFromSuperview()
                del self._items[iid]

        for inst in instances:
            if inst.instance_id in self._items:
                self._items[inst.instance_id].updateInstance_(inst)
            else:
                item = self._make_item(inst)
                self._items[inst.instance_id] = item
                self.addSubview_(item)

        if instances:
            if self._empty_label:
                self._empty_label.removeFromSuperview()
                self._empty_label = None
        else:
            self._ensure_empty_label()

        self._layout()
        self.setNeedsDisplay_(True)
        self.displayIfNeeded()

    def _ensure_empty_label(self) -> None:
        if self._empty_label:
            return
        self._empty_label = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 30, 160, 20))
        self._empty_label.setBezeled_(False)
        self._empty_label.setDrawsBackground_(False)
        self._empty_label.setEditable_(False)
        self._empty_label.setSelectable_(False)
        self._empty_label.setAlignment_(1)
        self._empty_label.setStringValue_("等待 AI 工具…")
        self._empty_label.setFont_(NSFont.systemFontOfSize_(12))
        self._empty_label.setTextColor_(NSColor.colorWithCalibratedWhite_alpha_(0.7, 1.0))
        self.addSubview_(self._empty_label)

    def _layout(self) -> None:
        item_w, item_h = self._item_size()
        x = PANEL_PAD_H
        for inst in self._instances:
            item = self._items.get(inst.instance_id)
            if item:
                item.setFrame_(NSMakeRect(x, PANEL_PAD_V + CLOSE_BTN, item_w, item_h))
                x += item_w + ITEM_GAP

        content_w = max(x + PANEL_PAD_H, 160)
        content_h = item_h + PANEL_PAD_V * 2 + CLOSE_BTN
        self.setFrameSize_(NSMakeSize(content_w, content_h))

        if self._empty_label:
            self._empty_label.setFrame_(NSMakeRect(0, content_h / 2 - 10, content_w, 20))

    def drawRect_(self, rect) -> None:
        PANEL_BG.setFill()
        bounds = self.bounds()
        from AppKit import NSBezierPath
        path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(bounds, 14, 14)
        path.fill()


class _CloseTarget(NSObject):
    """NSObject bridge so NSButton target/action works under PyObjC."""

    def initWithCallback_(self, callback):
        self = objc.super(_CloseTarget, self).init()
        if self is None:
            return None
        self._callback = callback
        return self

    def closeClicked_(self, sender) -> None:
        if self._callback:
            self._callback()


def _target_screen_frame():
    """Pick the screen where the mouse cursor is (most likely the active display)."""
    from AppKit import NSEvent, NSMouseInRect, NSScreen
    mouse = NSEvent.mouseLocation()
    for screen in NSScreen.screens():
        if NSMouseInRect(mouse, screen.frame(), False):
            return screen.visibleFrame()
    return NSScreen.mainScreen().visibleFrame()


class TrafficLightPanel:
    def __init__(self, on_close: Callable[[], None] | None = None) -> None:
        self._on_close = on_close
        self._container: TrafficLightContainerView | None = None
        self._panel: NSPanel | None = None
        self._close_btn: NSButton | None = None
        self._close_target = None
        self._click_target = ItemClickTarget.alloc().initWithCallback_(focus_instance)
        self._display_mode = get_display_mode()
        self._last_instances: list[MonitoredInstance] = []

    def set_display_mode(self, display_mode: str) -> None:
        if self._display_mode == display_mode:
            return
        self._display_mode = display_mode
        if self._container:
            self._container.setDisplayMode_(display_mode)
        if self._panel:
            self._panel.orderFrontRegardless()

    def get_display_mode(self) -> str:
        return self._display_mode

    def setup(self) -> NSPanel:
        screen = _target_screen_frame()
        init_item_h = KUN_ITEM_HEIGHT if self._display_mode != "traffic" else ITEM_HEIGHT
        init_w, init_h = 200, init_item_h + PANEL_PAD_V * 2 + CLOSE_BTN + 8
        # Center-top of primary screen — avoids off-screen on multi-monitor setups
        x = screen.origin.x + (screen.size.width - init_w) / 2
        y = screen.origin.y + screen.size.height - init_h - 48

        style = (
            NSWindowStyleMaskBorderless
            | NSWindowStyleMaskUtilityWindow
            | NSWindowStyleMaskNonactivatingPanel
        )
        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, init_w, init_h),
            style,
            NSBackingStoreBuffered,
            False,
        )
        panel.setLevel_(NSFloatingWindowLevel)
        panel.setOpaque_(False)
        panel.setBackgroundColor_(NSColor.clearColor())
        panel.setHasShadow_(True)
        panel.setFloatingPanel_(True)
        panel.setHidesOnDeactivate_(False)
        panel.setCollectionBehavior_(1 | 16 | 128)  # all spaces + fullscreen + stationary
        panel.setMovableByWindowBackground_(True)
        panel.setTitle_("Agent Light")
        panel.setIgnoresMouseEvents_(False)

        container = TrafficLightContainerView.alloc().initWithClickTarget_displayMode_(
            self._click_target, self._display_mode
        )
        container.setFrame_(NSMakeRect(0, 0, init_w, init_h))

        self._close_target = _CloseTarget.alloc().initWithCallback_(self._handle_close)
        close_btn = NSButton.alloc().initWithFrame_(NSMakeRect(init_w - CLOSE_BTN - 6, 4, CLOSE_BTN, CLOSE_BTN))
        close_btn.setBezelStyle_(NSBezelStyleSmallSquare)
        close_btn.setButtonType_(NSMomentaryChangeButton)
        close_btn.setTitle_("✕")
        close_btn.setFont_(NSFont.systemFontOfSize_(11))
        close_btn.setToolTip_("关闭 Agent Light")
        close_btn.setTarget_(self._close_target)
        close_btn.setAction_("closeClicked:")

        root = PanelRootView.alloc().initWithContainer_closeButton_(container, close_btn)
        root.setFrame_(NSMakeRect(0, 0, init_w, init_h))
        panel.setContentView_(root)
        self._close_btn = close_btn

        self._panel = panel
        self._container = container
        panel.orderFrontRegardless()
        logger.info(
            "Panel created at (%.0f, %.0f) size %dx%d [screen visibleFrame origin=(%.0f,%.0f) size=%.0fx%.0f]",
            x, y, init_w, init_h,
            screen.origin.x, screen.origin.y, screen.size.width, screen.size.height,
        )
        return panel

    def _handle_close(self) -> None:
        logger.info("Close button clicked")
        if self._on_close:
            self._on_close()

    def update(self, instances: list[MonitoredInstance]) -> None:
        if not self._container or not self._panel:
            return
        self._last_instances = list(instances)
        self._container.updateInstances_(instances)
        sz = self._container.frame().size
        self._panel.setContentSize_(NSMakeSize(sz.width, sz.height))
        root = self._panel.contentView()
        if root is not None:
            old_size = root.frame().size
            root.setFrameSize_(sz)
            root.resizeSubviewsWithOldSize_(old_size)
        self._panel.orderFrontRegardless()
        states = ", ".join(f"{i.display_name}={i.state.value}" for i in instances)
        logger.info("UI updated: %d instance(s) [%s]", len(instances), states or "none")
