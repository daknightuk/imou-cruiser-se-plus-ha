"""Config flow for Imou Cruiser SE Plus PTZ."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers import selector

from .client import ImouConnectionError, ImouNoPtzProfileError, ImouPtzClient
from .const import CONF_ONVIF_PORT, DEFAULT_ONVIF_PORT, DOMAIN


class ImouCruiserConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle setup through the Home Assistant UI."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect and validate local camera credentials."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            await self.async_set_unique_id(host.lower())
            self._abort_if_unique_id_configured()

            client = ImouPtzClient(
                host,
                user_input[CONF_ONVIF_PORT],
                user_input[CONF_USERNAME],
                user_input[CONF_PASSWORD],
            )
            try:
                presets = await client.get_presets()
            except ImouNoPtzProfileError:
                errors["base"] = "no_ptz_profile"
            except ImouConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=f"Imou Cruiser SE Plus ({host})",
                    data={**user_input, CONF_HOST: host},
                    description_placeholders={"preset_count": str(len(presets))},
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
                ),
                vol.Required(CONF_ONVIF_PORT, default=DEFAULT_ONVIF_PORT):
                    selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1, max=65535, mode=selector.NumberSelectorMode.BOX
                        )
                    ),
                vol.Required(CONF_USERNAME, default="admin"): selector.TextSelector(),
                vol.Required(CONF_PASSWORD): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)
