"""
Windows-only folder icon installer.

For each person folder:
  1. Generate `cluster_icon.ico` from the circular badge avatar (multi-size).
  2. Write `desktop.ini` referencing that icon.
  3. Set folder attribute READONLY (required for desktop.ini to be honored).
  4. Set desktop.ini attributes HIDDEN + SYSTEM.
  5. Trigger Explorer to re-read the folder icon.

All writes happen ONLY inside the provided folder_path. No touching of sources.
"""
import os
import sys
import logging
import ctypes
from typing import Optional, Tuple

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False

# Quality flag → ring color (RGBA)
QUALITY_COLORS = {
    "good":    (76, 175, 80, 255),    # green
    "fair":    (255, 193, 7, 255),    # amber
    "suspect": (255, 87, 34, 255),    # orange
    "poor":    (244, 67, 54, 255),    # red
    "single":  (158, 158, 158, 255),  # gray
}

logger = logging.getLogger(__name__)

IS_WINDOWS = sys.platform.startswith("win")

# File attribute constants (Win32)
FILE_ATTRIBUTE_READONLY = 0x01
FILE_ATTRIBUTE_HIDDEN   = 0x02
FILE_ATTRIBUTE_SYSTEM   = 0x04
INVALID_FILE_ATTRIBUTES = 0xFFFFFFFF

# SHChangeNotify constants
SHCNE_UPDATEITEM = 0x00002000
SHCNE_UPDATEDIR  = 0x00001000
SHCNE_ASSOCCHANGED = 0x08000000
SHCNF_PATHW      = 0x0005
SHCNF_IDLIST     = 0x0000

ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
             (128, 128), (256, 256)]


# ────────────────────────────────────────────────────────────────────────────
# ICO generation
# ────────────────────────────────────────────────────────────────────────────

def make_ico_from_badge(badge_png_path: str, ico_path: str) -> bool:
    """
    Convert the RGBA circular badge PNG into a multi-size .ico file.
    Returns True on success.
    """
    if not HAS_PILLOW:
        logger.error("[folder_icon] Pillow required for ICO generation")
        return False

    if not os.path.isfile(badge_png_path):
        logger.error(f"[folder_icon] Badge PNG missing: {badge_png_path}")
        return False

    try:
        img = Image.open(badge_png_path).convert("RGBA")
        # Ensure square + 256 minimum for highest DPI
        base = max(img.size)
        if img.size[0] != img.size[1]:
            side = base
            canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
            ox = (side - img.size[0]) // 2
            oy = (side - img.size[1]) // 2
            canvas.paste(img, (ox, oy), img)
            img = canvas
        if base < 256:
            img = img.resize((256, 256), Image.LANCZOS)

        img.save(ico_path, format="ICO", sizes=ICO_SIZES)
        return True
    except Exception as e:
        logger.error(f"[folder_icon] ICO generation failed: {e}")
        return False


# ────────────────────────────────────────────────────────────────────────────
# desktop.ini
# ────────────────────────────────────────────────────────────────────────────

DESKTOP_INI_TEMPLATE = (
    "[.ShellClassInfo]\r\n"
    "IconResource={ico_name},0\r\n"
    "IconFile={ico_name}\r\n"
    "IconIndex=0\r\n"
    "ConfirmFileOp=0\r\n"
    "InfoTip={info_tip}\r\n"
)


def write_desktop_ini(folder_path: str, ico_name: str, info_tip: str = "") -> Optional[str]:
    """
    Write desktop.ini in folder_path referencing ico_name (filename only).
    Uses UTF-16 LE with BOM — Explorer's preferred encoding for custom icons.
    """
    ini_path = os.path.join(folder_path, "desktop.ini")
    content = DESKTOP_INI_TEMPLATE.format(ico_name=ico_name, info_tip=info_tip)
    try:
        # UTF-16 LE with BOM
        with open(ini_path, "wb") as f:
            f.write(b"\xFF\xFE")
            f.write(content.encode("utf-16-le"))
        return ini_path
    except Exception as e:
        logger.error(f"[folder_icon] desktop.ini write failed: {e}")
        return None


# ────────────────────────────────────────────────────────────────────────────
# Win32 file attributes
# ────────────────────────────────────────────────────────────────────────────

def _get_attrs(path: str) -> int:
    if not IS_WINDOWS:
        return 0
    attrs = ctypes.windll.kernel32.GetFileAttributesW(path)
    return int(attrs) if attrs != INVALID_FILE_ATTRIBUTES else 0


def _set_attrs(path: str, attrs: int) -> bool:
    if not IS_WINDOWS:
        return False
    return bool(ctypes.windll.kernel32.SetFileAttributesW(path, attrs))


def apply_folder_icon_attributes(folder_path: str, desktop_ini_path: str) -> bool:
    """
    Set the NTFS attributes Explorer requires:
      - folder: +READONLY (marker that tells Explorer to read desktop.ini)
      - desktop.ini: +HIDDEN +SYSTEM
    """
    if not IS_WINDOWS:
        logger.info("[folder_icon] Skipping attribute set (non-Windows)")
        return False

    try:
        folder_attrs = _get_attrs(folder_path)
        _set_attrs(folder_path, folder_attrs | FILE_ATTRIBUTE_READONLY)

        ini_attrs = _get_attrs(desktop_ini_path)
        _set_attrs(
            desktop_ini_path,
            ini_attrs | FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM,
        )
        return True
    except Exception as e:
        logger.error(f"[folder_icon] attribute set failed: {e}")
        return False


# ────────────────────────────────────────────────────────────────────────────
# Icon cache refresh
# ────────────────────────────────────────────────────────────────────────────

def refresh_folder_icon(folder_path: str) -> None:
    """
    Tell Explorer to re-read this folder's icon without a full cache flush.
    Uses SHChangeNotify(SHCNE_UPDATEDIR, path). Non-destructive.
    """
    if not IS_WINDOWS:
        return
    try:
        ctypes.windll.shell32.SHChangeNotify(
            SHCNE_UPDATEDIR,
            SHCNF_PATHW,
            ctypes.c_wchar_p(folder_path),
            None,
        )
    except Exception as e:
        logger.debug(f"[folder_icon] SHChangeNotify failed for {folder_path}: {e}")


def refresh_association_cache() -> None:
    """
    Broader refresh — tells shell that icon associations changed.
    Run once after processing all folders.
    """
    if not IS_WINDOWS:
        return
    try:
        ctypes.windll.shell32.SHChangeNotify(
            SHCNE_ASSOCCHANGED, SHCNF_IDLIST, None, None
        )
    except Exception as e:
        logger.debug(f"[folder_icon] SHChangeNotify assoc failed: {e}")


# ────────────────────────────────────────────────────────────────────────────
# High-level convenience: one call installs icon on a folder
# ────────────────────────────────────────────────────────────────────────────

def install_folder_icon(folder_path: str, badge_png_path: str,
                         info_tip: str = "",
                         quality_flag: Optional[str] = None) -> bool:
    """
    Generate ICO + write desktop.ini + set attributes + refresh Explorer.
    If quality_flag given, decorates the badge with a colored ring.
    """
    if not os.path.isdir(folder_path):
        return False
    if not HAS_PILLOW:
        logger.error("[folder_icon] Pillow required")
        return False

    # Optionally decorate the badge with a quality ring before ICO conversion
    badge_for_ico = badge_png_path
    if quality_flag and quality_flag in QUALITY_COLORS:
        try:
            decorated = _decorate_with_quality_ring(badge_png_path, quality_flag)
            if decorated:
                badge_for_ico = decorated
        except Exception as e:
            logger.debug(f"[folder_icon] quality ring decorate failed: {e}")

    ico_path = os.path.join(folder_path, "cluster_icon.ico")
    if not make_ico_from_badge(badge_for_ico, ico_path):
        return False

    ini_path = write_desktop_ini(folder_path, "cluster_icon.ico", info_tip=info_tip)
    if not ini_path:
        return False

    if IS_WINDOWS:
        apply_folder_icon_attributes(folder_path, ini_path)
        refresh_folder_icon(folder_path)

    return True


def _decorate_with_quality_ring(badge_png_path: str, quality_flag: str) -> Optional[str]:
    """Add a colored outer ring to the badge based on cluster quality. Saves new PNG."""
    if not HAS_PILLOW:
        return None
    color = QUALITY_COLORS.get(quality_flag)
    if not color:
        return None

    img = Image.open(badge_png_path).convert("RGBA")
    w, h = img.size
    margin = max(2, min(w, h) // 32)
    out = Image.new("RGBA", (w + margin * 4, h + margin * 4), (0, 0, 0, 0))
    out.paste(img, (margin * 2, margin * 2), img)

    draw = ImageDraw.Draw(out)
    ring_w = max(3, min(w, h) // 24)
    ow = out.size[0]
    draw.ellipse(
        (ring_w // 2, ring_w // 2, ow - ring_w // 2 - 1, ow - ring_w // 2 - 1),
        outline=color, width=ring_w,
    )

    decorated_path = os.path.join(os.path.dirname(badge_png_path),
                                   "cluster_avatar_badge_ring.png")
    out.save(decorated_path, "PNG")
    return decorated_path


def make_initials_badge(initials: str, size: int = 256,
                         bg_color=(63, 81, 181, 255),
                         fg_color=(255, 255, 255, 255)) -> "Image.Image":
    """
    Generic fallback when no usable face: colored circle with initials.
    Used when a cluster's faces are all too low-quality for an avatar.
    """
    if not HAS_PILLOW:
        raise RuntimeError("Pillow required")

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((0, 0, size - 1, size - 1), fill=bg_color)

    text = (initials or "?")[:2].upper()
    # Best-effort font
    font = None
    for candidate in [
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/calibri.ttf",
    ]:
        try:
            font = ImageFont.truetype(candidate, size // 2)
            break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default()

    try:
        bbox = d.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    except Exception:
        tw, th = font.getsize(text) if hasattr(font, "getsize") else (size // 2, size // 2)

    d.text(((size - tw) / 2 - bbox[0] if 'bbox' in locals() else (size - tw) / 2,
            (size - th) / 2 - bbox[1] if 'bbox' in locals() else (size - th) / 2),
           text, fill=fg_color, font=font)
    return img
