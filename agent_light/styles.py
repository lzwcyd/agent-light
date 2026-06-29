"""Custom display styles — persistence, assets, image processing."""

from __future__ import annotations

import json
import logging
import re
import shutil
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from .constants import APP_DATA_DIR

logger = logging.getLogger(__name__)

SETTINGS_DIR = APP_DATA_DIR
STYLES_FILE = SETTINGS_DIR / "custom_styles.json"
STYLES_ROOT = SETTINGS_DIR / "styles"

DISPLAY_WIDTH = 80
DISPLAY_HEIGHT = 88

StateKey = Literal["running", "waiting", "idle"]
STATE_KEYS: tuple[StateKey, ...] = ("running", "waiting", "idle")
STATE_LABELS = {
    "running": "运行中",
    "waiting": "人工确认",
    "idle": "结束",
}

_EMOJI_RE = re.compile(
    r"^(?:"
    r"[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E0-\U0001F1FF"
    r"\U00002300-\U000023FF\U0000FE00-\U0000FE0F\U0000200D\U0001F3FB-\U0001F3FF"
    r"\U0001F900-\U0001F9FF\U0001FA70-\U0001FAFF]+"
    r")+$"
)

_IMAGE_SUFFIXES = {".gif", ".png", ".jpg", ".jpeg", ".webp"}


@dataclass
class CustomStyle:
    id: str
    name: str
    banner_emoji: str
    assets: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> CustomStyle:
        return cls(
            id=str(data.get("id", uuid.uuid4().hex)),
            name=str(data.get("name", "未命名")).strip() or "未命名",
            banner_emoji=str(data.get("banner_emoji", "🎨")),
            assets={
                str(k): str(v)
                for k, v in (data.get("assets") or {}).items()
                if k in STATE_KEYS and v
            },
        )


_styles: list[CustomStyle] = []
_loaded = False


def _load_all() -> None:
    global _styles, _loaded
    if _loaded:
        return
    try:
        if STYLES_FILE.exists():
            raw = json.loads(STYLES_FILE.read_text(encoding="utf-8"))
            items = raw if isinstance(raw, list) else raw.get("styles", [])
            _styles = [CustomStyle.from_dict(item) for item in items if isinstance(item, dict)]
        else:
            _styles = []
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("Failed to load custom styles: %s", exc)
        _styles = []
    _loaded = True


def _save_all() -> None:
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    STYLES_FILE.write_text(
        json.dumps([s.to_dict() for s in _styles], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def list_styles() -> list[CustomStyle]:
    _load_all()
    return list(_styles)


def get_style(style_id: str) -> CustomStyle | None:
    _load_all()
    for style in _styles:
        if style.id == style_id:
            return style
    return None


def validate_emoji(value: str) -> bool:
    text = value.strip()
    if not text or len(text) > 8:
        return False
    return bool(_EMOJI_RE.match(text))


def validate_name(name: str) -> bool:
    return bool(name.strip())


def style_dir(style_id: str) -> Path:
    return STYLES_ROOT / style_id


def asset_path(style_id: str, state: StateKey) -> Path:
    style = get_style(style_id)
    if not style:
        return style_dir(style_id) / f"{state}.png"
    filename = style.assets.get(state) or f"{state}.png"
    return style_dir(style_id) / filename


def asset_paths(style_id: str) -> dict[StateKey, Path]:
    return {state: asset_path(style_id, state) for state in STATE_KEYS}


def is_animated_file(path: Path) -> bool:
    return path.suffix.lower() == ".gif"


def _resize_static_image(src: Path, dest: Path) -> None:
    from PIL import Image, ImageOps

    dest.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as img:
        img = img.convert("RGBA")
        fitted = ImageOps.fit(img, (DISPLAY_WIDTH, DISPLAY_HEIGHT), Image.Resampling.LANCZOS)
        suffix = dest.suffix.lower()
        if suffix in (".jpg", ".jpeg"):
            fitted.convert("RGB").save(dest, quality=90)
        else:
            fitted.save(dest, optimize=True)


def _resize_gif(src: Path, dest: Path) -> None:
    from PIL import Image, ImageOps, ImageSequence

    dest.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as img:
        frames: list[Image.Image] = []
        durations: list[int] = []
        for frame in ImageSequence.Iterator(img):
            rgba = frame.convert("RGBA")
            fitted = ImageOps.fit(rgba, (DISPLAY_WIDTH, DISPLAY_HEIGHT), Image.Resampling.LANCZOS)
            frames.append(fitted)
            durations.append(frame.info.get("duration", img.info.get("duration", 80)))

        if not frames:
            _resize_static_image(src, dest.with_suffix(".png"))
            return

        frames[0].save(
            dest,
            save_all=True,
            append_images=frames[1:],
            loop=0,
            duration=durations,
            disposal=2,
            optimize=False,
        )


def import_state_asset(style_id: str, state: StateKey, src: Path) -> Path:
    """Copy + resize uploaded image/gif into the style directory."""
    src = Path(src)
    if src.suffix.lower() not in _IMAGE_SUFFIXES:
        raise ValueError(f"不支持的文件格式: {src.suffix}")

    is_gif = src.suffix.lower() == ".gif"
    dest_name = f"{state}.gif" if is_gif else f"{state}.png"
    dest = style_dir(style_id) / dest_name

    if is_gif:
        _resize_gif(src, dest)
    else:
        _resize_static_image(src, dest)

    _load_all()
    for style in _styles:
        if style.id == style_id:
            style.assets[state] = dest_name
            break
    _save_all()
    logger.info("Imported %s asset for style %s → %s", state, style_id, dest)
    return dest


def is_style_complete(style_id: str) -> bool:
    style = get_style(style_id)
    if not style:
        return False
    ok, _ = validate_style_draft(style.name, style.banner_emoji, style_id)
    return ok


def validate_style_draft(
    name: str,
    banner_emoji: str,
    style_id: str,
) -> tuple[bool, str]:
    if not validate_name(name):
        return False, "请填写风格名称"
    if not validate_emoji(banner_emoji):
        return False, "Banner 图标必须是 emoji（仅 emoji）"
    missing: list[str] = []
    for state in STATE_KEYS:
        if not asset_path(style_id, state).is_file():
            missing.append(STATE_LABELS[state])
    if missing:
        return False, "以下状态素材为必填项： " + "、".join(missing)
    return True, ""


def save_style_complete(style_id: str, *, name: str, banner_emoji: str) -> CustomStyle:
    ok, message = validate_style_draft(name, banner_emoji, style_id)
    if not ok:
        raise ValueError(message)
    style = update_style(style_id, name=name, banner_emoji=banner_emoji)
    return style


def list_complete_styles() -> list[CustomStyle]:
    return [s for s in list_styles() if is_style_complete(s.id)]


def create_style(name: str, banner_emoji: str) -> CustomStyle:
    if not validate_name(name):
        raise ValueError("风格名称不能为空")
    if not validate_emoji(banner_emoji):
        raise ValueError("Banner 图标必须是 emoji")

    _load_all()
    style = CustomStyle(
        id=uuid.uuid4().hex[:12],
        name=name.strip(),
        banner_emoji=banner_emoji.strip(),
    )
    _styles.append(style)
    style_dir(style.id).mkdir(parents=True, exist_ok=True)
    _save_all()
    return style


def update_style(style_id: str, *, name: str | None = None, banner_emoji: str | None = None) -> CustomStyle:
    _load_all()
    for style in _styles:
        if style.id != style_id:
            continue
        if name is not None:
            if not validate_name(name):
                raise ValueError("风格名称不能为空")
            style.name = name.strip()
        if banner_emoji is not None:
            if not validate_emoji(banner_emoji):
                raise ValueError("Banner 图标必须是 emoji")
            style.banner_emoji = banner_emoji.strip()
        _save_all()
        return style
    raise KeyError(f"style not found: {style_id}")


def delete_style(style_id: str) -> None:
    global _styles
    _load_all()
    _styles = [s for s in _styles if s.id != style_id]
    _save_all()
    folder = style_dir(style_id)
    if folder.is_dir():
        shutil.rmtree(folder, ignore_errors=True)


def reload_styles() -> None:
    global _loaded
    _loaded = False
    _load_all()
