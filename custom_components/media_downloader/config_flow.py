from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import (
    BooleanSelector,
    TextSelector,
    TextSelectorConfig,
)
from .const import (
    DOMAIN,
    CONF_DOWNLOAD_DIR,
    CONF_OVERWRITE,
    DEFAULT_OVERWRITE,
)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_DOWNLOAD_DIR): str,  # ruta absoluta recomendada: /media o subcarpeta
        vol.Optional(CONF_OVERWRITE, default=DEFAULT_OVERWRITE): bool,
    }
)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=STEP_USER_DATA_SCHEMA)

        title = f"Media Downloader ({user_input[CONF_DOWNLOAD_DIR]})"
        return self.async_create_entry(title=title, data=user_input)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return OptionsFlow(config_entry)


class OptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        download_dir = self.config_entry.options.get(
            CONF_DOWNLOAD_DIR, self.config_entry.data.get(CONF_DOWNLOAD_DIR, "")
        )
        overwrite = self.config_entry.options.get(
            CONF_OVERWRITE, self.config_entry.data.get(CONF_OVERWRITE, DEFAULT_OVERWRITE)
        )

        schema = vol.Schema(
            {
                vol.Required(CONF_DOWNLOAD_DIR, default=download_dir): str,
                vol.Optional(CONF_OVERWRITE, default=overwrite): bool,
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
