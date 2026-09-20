"""Imou Cruiser SE Plus PTZ integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant

from .client import ImouPtzClient
from .const import CONF_ONVIF_PORT, DEFAULT_ONVIF_PORT, DOMAIN

type ImouConfigEntry = ConfigEntry[ImouPtzClient]


async def async_setup_entry(hass: HomeAssistant, entry: ImouConfigEntry) -> bool:
    """Set up the integration from a config entry."""
    entry.runtime_data = ImouPtzClient(
        entry.data[CONF_HOST],
        entry.data.get(CONF_ONVIF_PORT, DEFAULT_ONVIF_PORT),
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
    )
    await hass.config_entries.async_forward_entry_setups(
        entry, [Platform.BUTTON, Platform.SWITCH]
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ImouConfigEntry) -> bool:
    """Unload the integration."""
    return await hass.config_entries.async_unload_platforms(
        entry, [Platform.BUTTON, Platform.SWITCH]
    )
