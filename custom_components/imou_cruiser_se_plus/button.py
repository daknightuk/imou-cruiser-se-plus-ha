"""Preset buttons for Imou Cruiser SE Plus cameras."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import ImouConnectionError, ImouPreset, ImouPtzClient
from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[ImouPtzClient],
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Discover presets and create one button per preset."""
    client = entry.runtime_data
    presets = await client.get_presets()
    entities: list[ButtonEntity] = [
        ImouPresetButton(entry, client, preset) for preset in presets
    ]
    try:
        status = await hass.async_add_executor_job(client.get_deterrence_status)
    except ImouConnectionError:
        status = {}
    if "siren" in status:
        entities.extend(
            [
                ImouSirenButton(entry, client, True),
                ImouSirenButton(entry, client, False),
            ]
        )
    async_add_entities(entities)


class ImouPresetButton(ButtonEntity):
    """A button that moves the camera to one preset."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:camera-control"

    def __init__(
        self,
        entry: ConfigEntry[ImouPtzClient],
        client: ImouPtzClient,
        preset: ImouPreset,
    ) -> None:
        self._client = client
        self._preset = preset
        self._attr_name = preset.name
        self._attr_unique_id = f"{entry.entry_id}_{preset.token}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Imou",
            model="Cruiser SE Plus",
            configuration_url=f"http://{entry.data[CONF_HOST]}",
        )

    async def async_press(self) -> None:
        """Move to this preset."""
        try:
            await self._client.goto_preset(self._preset.token)
        except ImouConnectionError as err:
            raise HomeAssistantError(
                f"Unable to move to preset {self._preset.name}: {err}"
            ) from err


class ImouSirenButton(ButtonEntity):
    """Start or stop the camera's built-in siren."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:alarm-light"

    def __init__(
        self,
        entry: ConfigEntry[ImouPtzClient],
        client: ImouPtzClient,
        enabled: bool,
    ) -> None:
        self._client = client
        self._enabled = enabled
        self._attr_name = "Trigger siren" if enabled else "Stop siren"
        action = "start" if enabled else "stop"
        self._attr_unique_id = f"{entry.entry_id}_siren_{action}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Imou",
            model="Cruiser SE Plus",
            configuration_url=f"http://{entry.data[CONF_HOST]}",
        )

    async def async_press(self) -> None:
        """Start or stop the siren."""
        try:
            await self.hass.async_add_executor_job(
                self._client.set_siren, self._enabled
            )
        except ImouConnectionError as err:
            raise HomeAssistantError(f"Unable to control the siren: {err}") from err
