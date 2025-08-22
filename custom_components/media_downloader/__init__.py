from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from typing import Optional

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import aiohttp_client, config_validation as cv
from homeassistant.exceptions import HomeAssistantError

from .const import (
    DOMAIN,
    CONF_DOWNLOAD_DIR,
    CONF_OVERWRITE,
    DEFAULT_OVERWRITE,
    SERVICE_DOWNLOAD_FILE,
    ATTR_URL,
    ATTR_SUBDIR,
    ATTR_FILENAME,
    ATTR_OVERWRITE,
    ATTR_TIMEOUT,
    EVENT_DOWNLOAD_STARTED,
    EVENT_DOWNLOAD_COMPLETED,
)


PLATFORMS: list = []  # no entities por ahora; solo servicios


def _sanitize_filename(name: str) -> str:
    # Quita caracteres problemáticos y normaliza espacios
    name = name.strip()
    name = re.sub(r"[\\/:*?\"<>|\r\n\t]", "_", name)
    # evita nombres vacíos
    return name or "downloaded_file"


def _ensure_within_base(base: Path, target: Path) -> None:
    try:
        target.relative_to(base)
    except Exception:
        raise HomeAssistantError(f"Ruta fuera del directorio permitido: {target}")


def _guess_filename_from_url(url: str) -> str:
    # intento simple: toma lo que sigue al último "/"
    tail = url.split("?")[0].rstrip("/").split("/")[-1]
    return _sanitize_filename(tail or "downloaded_file")


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Config entry setup."""
    hass.data.setdefault(DOMAIN, {})

    @callback
    def _get_config() -> tuple[Path, bool]:
        download_dir = Path(
            entry.options.get(CONF_DOWNLOAD_DIR, entry.data.get(CONF_DOWNLOAD_DIR))
        )
        overwrite = bool(
            entry.options.get(CONF_OVERWRITE, entry.data.get(CONF_OVERWRITE, DEFAULT_OVERWRITE))
        )
        return (download_dir, overwrite)

    async def _async_download(call: ServiceCall) -> None:
        url: str = call.data[ATTR_URL]
        subdir: Optional[str] = call.data.get(ATTR_SUBDIR)
        filename: Optional[str] = call.data.get(ATTR_FILENAME)
        overwrite: Optional[bool] = call.data.get(ATTR_OVERWRITE)
        timeout_sec: int = int(call.data.get(ATTR_TIMEOUT, 300))

        base_dir, default_overwrite = _get_config()
        # Validación de base_dir
        base_dir = base_dir.resolve()

        # Construye destino
        if subdir:
            # sanea subdir para evitar traversal
            safe_subdir = Path(_sanitize_filename(subdir))
            dest_dir = (base_dir / safe_subdir).resolve()
        else:
            dest_dir = base_dir

        # Asegura que esté dentro de base_dir
        _ensure_within_base(base_dir, dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)

        # Nombre de archivo final
        final_name = _sanitize_filename(filename) if filename else _guess_filename_from_url(url)
        dest_path = (dest_dir / final_name).resolve()
        _ensure_within_base(base_dir, dest_path)

        # Política de overwrite
        do_overwrite = default_overwrite if overwrite is None else bool(overwrite)

        # Evento de inicio
        hass.bus.async_fire(
            EVENT_DOWNLOAD_STARTED,
            {
                "url": url,
                "path": str(dest_path),
                "overwrite": do_overwrite,
            },
        )

        session: aiohttp.ClientSession = aiohttp_client.async_get_clientsession(hass)

        tmp_path = dest_path.with_suffix(dest_path.suffix + ".part")

        # Evita colisiones de temporales
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass

        try:
            # Timeout total de descarga
            async with asyncio.timeout(timeout_sec):
                async with session.get(url) as resp:
                    if resp.status != 200:
                        raise HomeAssistantError(f"Error HTTP {resp.status} al descargar: {url}")

                    # Si no hay filename explícito, intenta extraer de Content-Disposition
                    if not filename:
                        cd = resp.headers.get("Content-Disposition") or resp.headers.get("content-disposition")
                        if cd:
                            # filename="name.ext"
                            m = re.search(r'filename\*=.*?\'\'([^;]+)|filename="?([^";]+)"?', cd)
                            if m:
                                candidate = m.group(1) or m.group(2)
                                if candidate:
                                    final_name_cd = _sanitize_filename(candidate)
                                    dest_path = (dest_dir / final_name_cd).resolve()
                                    _ensure_within_base(base_dir, dest_path)
                                    tmp_path = dest_path.with_suffix(dest_path.suffix + ".part")

                    # Overwrite policy
                    if dest_path.exists() and not do_overwrite:
                        raise HomeAssistantError(f"El archivo ya existe y overwrite=false: {dest_path}")

                    # Escribe en streaming
                    with open(tmp_path, "wb") as f:
                        async for chunk in resp.content.iter_chunked(1024 * 64):
                            if chunk:
                                f.write(chunk)

            # Reemplazo atómico
            if dest_path.exists() and do_overwrite:
                os.replace(tmp_path, dest_path)
            else:
                # mv si no existía
                os.rename(tmp_path, dest_path)

            # Evento de completado (éxito)
            hass.bus.async_fire(
                EVENT_DOWNLOAD_COMPLETED,
                {
                    "url": url,
                    "path": str(dest_path),
                    "success": True,
                    "error": None,
                },
            )

        except Exception as e:
            # Limpia temporal y emite evento de error
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except Exception:
                pass

            hass.bus.async_fire(
                EVENT_DOWNLOAD_COMPLETED,
                {
                    "url": url,
                    "path": str(dest_path),
                    "success": False,
                    "error": str(e),
                },
            )
            raise

    # Registro del servicio
    hass.services.async_register(
        DOMAIN,
        SERVICE_DOWNLOAD_FILE,
        _async_download,
        schema=vol.Schema(
            {
                vol.Required(ATTR_URL): cv.url,
                vol.Optional(ATTR_SUBDIR): cv.string,
                vol.Optional(ATTR_FILENAME): cv.string,
                vol.Optional(ATTR_OVERWRITE): cv.boolean,
                vol.Optional(ATTR_TIMEOUT): vol.Coerce(int),
            }
        ),
    )

    # Manejo de recarga de opciones
    async def _options_updated(_):
        await hass.config_entries.async_reload(entry.entry_id)

    entry.async_on_unload(entry.add_update_listener(_options_updated))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    # Solo servicios; nada que descargar de PLATFORMS
    hass.services.async_remove(DOMAIN, SERVICE_DOWNLOAD_FILE)
    return True
