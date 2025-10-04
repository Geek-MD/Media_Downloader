from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Optional, Tuple

_LOGGER = logging.getLogger(__name__)


# ----------------------------- helpers ----------------------------- #

def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    """Run a subprocess command, raising on non-zero exit."""
    _LOGGER.debug("Running command: %s", " ".join(cmd))
    return subprocess.run(cmd, capture_output=True, text=True, check=True)


def _safe_replace(src: Path, dst: Path) -> None:
    """Atomically replace dst with src."""
    src.replace(dst)


def _probe_dimensions(path: Path) -> Optional[Tuple[int, int]]:
    """Return (width, height) using ffprobe JSON; fallback to None."""
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "json",
            str(path),
        ]
        res = _run(cmd)
        data = json.loads(res.stdout or "{}")
        streams = data.get("streams", [])
        if streams:
            w = int(streams[0].get("width") or 0)
            h = int(streams[0].get("height") or 0)
            if w > 0 and h > 0:
                return (w, h)
    except Exception as err:
        _LOGGER.warning("ffprobe failed for %s: %s", path, err)
    return None


# --------------------------- public utils --------------------------- #

def sanitize_filename(filename: str) -> str:
    """Sanitize filename by removing risky characters."""
    keep = set(" ._-()[]")
    return "".join(c for c in filename if c.isalnum() or c in keep).strip() or "downloaded_file"


def ensure_within_base(base: Path, path: Path) -> None:
    """Ensure 'path' is inside 'base' (security)."""
    try:
        path.resolve().relative_to(base.resolve())
    except Exception as err:
        raise ValueError(f"Path {path} is outside of base directory {base}") from err


def guess_filename_from_url(url: str) -> str:
    """Best-effort filename from URL."""
    part = url.split("?")[0].rstrip("/").split("/")[-1] or "downloaded_file"
    return sanitize_filename(part)


def optional_resize_video(path: Path, width: int, height: int) -> bool:
    """
    If the video is not width x height, re-encode to those exact dimensions,
    enforcing SAR=1 and correct DAR. Returns True if resized or already OK.
    """
    dims = _probe_dimensions(path)
    if dims and dims == (width, height):
        _LOGGER.debug("Skip resize: %s already %dx%d", path, width, height)
        return True

    try:
        tmp = path.with_suffix(".resize.mp4")
        vf = f"scale={width}:{height},setsar=1,setdar={width}/{height}"
        cmd = [
            "ffmpeg", "-y",
            "-i", str(path),
            "-vf", vf,
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast", "-crf", "20",
            "-c:a", "copy",
            str(tmp),
        ]
        _run(cmd)
        _safe_replace(tmp, path)
        _LOGGER.info("Resized video to %dx%d: %s", width, height, path)
        return True
    except Exception as err:
        _LOGGER.error("Resize failed for %s: %s", path, err)
        return False


def embed_clean_thumbnail(path: Path, width_hint: Optional[int] = None, height_hint: Optional[int] = None) -> bool:
    """
    Generate a clean JPEG thumbnail and embed it as attached_pic.
    Width/height hints help keep the same AR; they are optional.
    """
    try:
        w = width_hint
        h = height_hint
        if not (w and h):
            dims = _probe_dimensions(path)
            if dims:
                w, h = dims

        # Default thumbnail size: try to keep AR, fall back to 320w
        thumb = path.with_suffix(".thumb.jpg")
        scale_arg = "320:-1"
        if w and h and w > 0 and h > 0:
            # downscale keeping AR to a reasonable preview height ~180
            # (Telegram only needs a representative frame, not exact dims)
            target_w = 320
            target_h = max(1, int(round(target_w * h / w)))
            scale_arg = f"{target_w}:{target_h}"

        # 1) Extract frame as thumbnail
        cmd_thumb = [
            "ffmpeg", "-y",
            "-ss", "00:00:00.500",  # early frame, after first half second
            "-i", str(path),
            "-vframes", "1",
            "-vf", f"scale={scale_arg}",
            str(thumb),
        ]
        _run(cmd_thumb)

        # 2) Re-mux with the thumbnail attached (strip existing attached_pic)
        tmp = path.with_suffix(".thumb.mp4")
        cmd_embed = [
            "ffmpeg", "-y",
            "-i", str(path),
            "-i", str(thumb),
            "-map", "0", "-map", "1",
            "-map", "-0:v:m:attached_pic",
            "-c", "copy",
            "-disposition:v:1", "attached_pic",
            "-movflags", "+faststart",
            str(tmp),
        ]
        _run(cmd_embed)
        _safe_replace(tmp, path)
        try:
            thumb.unlink()
        except Exception:
            pass

        _LOGGER.debug("Embedded thumbnail into %s", path)
        return True
    except Exception as err:
        _LOGGER.error("Thumbnail embedding failed for %s: %s", path, err)
        return False


def fix_telegram_aspect(path: Path) -> bool:
    """
    Final compatibility pass for Telegram:
      - Strip any existing attached_pic.
      - Ensure moov atom at the start (+faststart).
      - Normalize SAR=1 (square pixels) via a lightweight re-encode when needed.
      - Re-mux to MP4 cleanly.
      - Re-embed a clean thumbnail.

    Returns True if succeeded (best-effort even if some steps fail).
    """
    ok = True

    # A) Strip existing attached_pic & faststart via stream copy
    try:
        tmp_a = path.with_suffix(".tga.mp4")
        cmd_a = [
            "ffmpeg", "-y",
            "-i", str(path),
            "-map", "0",
            "-map", "-0:v:m:attached_pic",
            "-c", "copy",
            "-movflags", "+faststart",
            str(tmp_a),
        ]
        _run(cmd_a)
        _safe_replace(tmp_a, path)
    except Exception as err:
        _LOGGER.warning("Clean remux (A) failed for %s: %s", path, err)
        ok = False

    # B) If SAR != 1 or DAR oddities suspected, re-encode tiny pass with setsar=1
    try:
        dims = _probe_dimensions(path)
        vf = "setsar=1"
        if dims and (dims[0] > 0 and dims[1] > 0):
            vf = f"setsar=1,setdar={dims[0]}/{dims[1]}"

        tmp_b = path.with_suffix(".tgb.mp4")
        cmd_b = [
            "ffmpeg", "-y",
            "-i", str(path),
            "-vf", vf,
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast", "-crf", "23",
            "-c:a", "copy",
            "-movflags", "+faststart",
            str(tmp_b),
        ]
        _run(cmd_b)
        _safe_replace(tmp_b, path)
    except Exception as err:
        _LOGGER.warning("Aspect normalize (B) failed for %s: %s", path, err)
        ok = False

    # C) Re-embed clean thumbnail (best-effort)
    dims = _probe_dimensions(path)
    if not embed_clean_thumbnail(path, *(dims or (None, None))):
        ok = False

    return ok
