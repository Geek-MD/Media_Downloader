"""Video utilities for Media Downloader integration."""

from __future__ import annotations

import os
import re
import json
import subprocess
import logging
from pathlib import Path
from homeassistant.exceptions import HomeAssistantError

_LOGGER = logging.getLogger(__name__)


# --------------------------------------------------------
# 🧩 Generic path and filename utilities
# --------------------------------------------------------

def sanitize_filename(name: str) -> str:
    """Clean and sanitize a filename for safe filesystem usage."""
    name = name.strip()
    name = re.sub(r"[\\/:*?\"<>|\r\n\t]", "_", name)
    return name or "downloaded_file"


def ensure_within_base(base: Path, target: Path) -> None:
    """Ensure a path is inside the allowed base directory."""
    try:
        target.relative_to(base)
    except Exception as err:
        raise HomeAssistantError(f"Path {target} is outside of base directory {base}") from err


def guess_filename_from_url(url: str) -> str:
    """Guess a safe filename from a URL."""
    tail = url.split("?")[0].rstrip("/").split("/")[-1]
    return sanitize_filename(tail or "downloaded_file")


# --------------------------------------------------------
# 🧩 Video metadata and manipulation
# --------------------------------------------------------

def get_video_dimensions(path: Path) -> tuple[int, int]:
    """Return (width, height) using ffprobe, fallback to ffmpeg."""
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "json", str(path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        streams = data.get("streams", [])
        if streams:
            width = int(streams[0].get("width", 0))
            height = int(streams[0].get("height", 0))
            if width > 0 and height > 0:
                return width, height
    except Exception as err:
        _LOGGER.warning("ffprobe failed for %s: %s", path, err)

    # fallback using ffmpeg -i
    try:
        cmd = ["ffmpeg", "-i", str(path)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        match = re.search(r",\s*(\d{2,5})x(\d{2,5})", result.stderr)
        if match:
            return int(match.group(1)), int(match.group(2))
    except Exception as err:
        _LOGGER.warning("ffmpeg fallback failed for %s: %s", path, err)

    return (0, 0)


def normalize_video_aspect(path: Path) -> bool:
    """Normalize video aspect ratio to prevent square appearance in Telegram."""
    tmp_file = path.with_suffix(".normalized" + path.suffix)
    try:
        w, h = get_video_dimensions(path)
        if w == 0 or h == 0:
            _LOGGER.warning("Could not determine video dimensions for %s", path)
            return False

        cmd = [
            "ffmpeg", "-y", "-i", str(path),
            "-vf", f"setsar=1,setdar={w}/{h}",
            "-c:v", "libx264", "-preset", "veryfast",
            "-crf", "18", "-c:a", "copy",
            str(tmp_file)
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=300)
        os.replace(tmp_file, path)
        _LOGGER.info("Aspect ratio normalized for %s", path)
        return True
    except Exception as err:
        _LOGGER.warning("Aspect normalization failed for %s: %s", path, err)
        if tmp_file.exists():
            tmp_file.unlink(missing_ok=True)
        return False


def embed_thumbnail(path: Path) -> bool:
    """Generate and embed a thumbnail to ensure Telegram uses correct preview."""
    thumb_path = path.with_suffix(".jpg")
    tmp_output = path.with_suffix(".thumb" + path.suffix)
    try:
        # Extract the first frame as thumbnail
        subprocess.run([
            "ffmpeg", "-y", "-i", str(path),
            "-vf", "select=eq(n\\,0)", "-vframes", "1",
            str(thumb_path)
        ], check=True, capture_output=True, text=True, timeout=60)

        if not thumb_path.exists():
            _LOGGER.warning("Thumbnail generation failed for %s", path)
            return False

        subprocess.run([
            "ffmpeg", "-y",
            "-i", str(path),
            "-i", str(thumb_path),
            "-map", "0", "-map", "1",
            "-c", "copy",
            "-disposition:v:1", "attached_pic",
            str(tmp_output)
        ], check=True, capture_output=True, text=True, timeout=120)

        os.replace(tmp_output, path)
        thumb_path.unlink(missing_ok=True)
        _LOGGER.info("Thumbnail embedded for %s", path)
        return True

    except Exception as err:
        _LOGGER.warning("Thumbnail embedding failed for %s: %s", path, err)
        if thumb_path.exists():
            thumb_path.unlink(missing_ok=True)
        if tmp_output.exists():
            tmp_output.unlink(missing_ok=True)
        return False


def resize_video(path: Path, width: int, height: int) -> bool:
    """Resize video to target dimensions if needed."""
    tmp_resized = path.with_suffix(".resized" + path.suffix)
    cmd = [
        "ffmpeg", "-y", "-i", str(path),
        "-vf", f"scale={width}:{height},setsar=1,setdar={width}/{height}",
        "-c:a", "copy",
        str(tmp_resized)
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=300)
        os.replace(tmp_resized, path)
        _LOGGER.info("Video resized successfully: %s", path)
        return True
    except Exception as err:
        _LOGGER.error("Video resize failed for %s: %s", path, err)
        if tmp_resized.exists():
            tmp_resized.unlink(missing_ok=True)
        return False
