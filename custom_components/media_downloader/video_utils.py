from __future__ import annotations

import os
import re
import subprocess
import json
import logging
from pathlib import Path

from homeassistant.exceptions import HomeAssistantError

_LOGGER = logging.getLogger(__name__)


# ------------------- Utilidades generales -------------------

def _sanitize_filename(name: str) -> str:
    """Clean invalid characters from filename."""
    name = name.strip()
    name = re.sub(r"[\\/:*?\"<>|\r\n\t]", "_", name)
    return name or "downloaded_file"


def _ensure_within_base(base: Path, target: Path) -> None:
    """Ensure that a target path is inside the allowed base directory."""
    try:
        target.relative_to(base)
    except Exception:
        raise HomeAssistantError(f"Path outside allowed base directory: {target}")


def _guess_filename_from_url(url: str) -> str:
    """Guess filename from URL if not explicitly provided."""
    tail = url.split("?")[0].rstrip("/").split("/")[-1]
    return _sanitize_filename(tail or "downloaded_file")


# ------------------- Procesamiento de video -------------------

def _get_video_dimensions(path: Path) -> tuple[int, int]:
    """Return video dimensions (width, height) using ffprobe with ffmpeg fallback."""
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
        _LOGGER.warning("ffprobe failed to get dimensions for %s: %s", path, err)

    try:
        cmd = ["ffmpeg", "-i", str(path)]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        match = re.search(r",\s*(\d{2,5})x(\d{2,5})", result.stderr)
        if match:
            return int(match.group(1)), int(match.group(2))
    except Exception as err:
        _LOGGER.warning("ffmpeg fallback failed for %s: %s", path, err)

    return (0, 0)


def _resize_video(path: Path, width: int, height: int) -> bool:
    """Resize video to given width and height."""
    tmp_resized = path.with_suffix(".resized" + path.suffix)
    cmd = [
        "ffmpeg", "-y", "-i", str(path),
        "-vf", f"scale={width}:{height},setsar=1,setdar={width}/{height}",
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(tmp_resized)
    ]
    try:
        subprocess.run(cmd, check=True)
        os.replace(tmp_resized, path)
        return True
    except Exception as err:
        _LOGGER.error("Resize failed for %s: %s", path, err)
        if tmp_resized.exists():
            tmp_resized.unlink()
        return False


def _embed_thumbnail(path: Path) -> bool:
    """Generate and embed a thumbnail to avoid Telegram square preview."""
    tmp_thumb = path.with_suffix(".thumb" + path.suffix)
    try:
        cmd = [
            "ffmpeg", "-y", "-i", str(path),
            "-map", "0",
            "-c", "copy",
            "-map_metadata", "0",
            "-movflags", "+faststart",
            "-vf", "thumbnail,scale=320:180",
            str(tmp_thumb),
        ]
        subprocess.run(cmd, check=True)
        os.replace(tmp_thumb, path)
        return True
    except Exception as err:
        _LOGGER.error("Thumbnail embedding failed for %s: %s", path, err)
        if tmp_thumb.exists():
            tmp_thumb.unlink()
        return False


def _postprocess_video(path: Path) -> bool:
    """Normalize video stream to fix display/aspect ratio issues."""
    tmp_fixed = path.with_suffix(".fixed" + path.suffix)
    try:
        cmd = [
            "ffmpeg", "-y", "-i", str(path),
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-vf", "setsar=1",
            "-movflags", "+faststart",
            str(tmp_fixed),
        ]
        subprocess.run(cmd, check=True)
        os.replace(tmp_fixed, path)
        return True
    except Exception as err:
        _LOGGER.error("Postprocess failed for %s: %s", path, err)
        if tmp_fixed.exists():
            tmp_fixed.unlink()
        return False
