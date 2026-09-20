"""Deterrence light switch for Imou Cruiser SE Plus cameras."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import ImouConnectionError, ImouPtzClient
from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[ImouPtzClient],
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create a light control only when the camera advertises it."""
    client = entry.runtime_data
    try:
        status = await hass.async_add_executor_job(client.get_deterrence_status)
    except ImouConnectionError:
        return
    if "warning_light" in status:
        async_add_entities(
            [ImouWarningLightSwitch(entry, client, status["warning_light"])]
        )


class ImouWarningLightSwitch(SwitchEntity):
    """Control the camera's visible warning/spotlight output."""

    _attr_has_entity_name = True
    _attr_name = "Warning light"
    _attr_icon = "mdi:spotlight-beam"

    def __init__(
        self,
        entry: ConfigEntry[ImouPtzClient],
        client: ImouPtzClient,
        initial_state: bool,
    ) -> None:
        self._client = client
        self._attr_is_on = initial_state
        self._attr_unique_id = f"{entry.entry_id}_warning_light"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Imou",
            model="Cruiser SE Plus",
            configuration_url=f"http://{entry.data[CONF_HOST]}",
        )

    async def _async_set(self, enabled: bool) -> None:
        try:
            await self.hass.async_add_executor_job(
                self._client.set_warning_light, enabled
            )
        except ImouConnectionError as err:
            raise HomeAssistantError(
                f"Unable to control the warning light: {err}"
            ) from err
        self._attr_is_on = enabled
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: object) -> None:
        """Turn on the warning light."""
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: object) -> None:
        """Turn off the warning light."""
        await self._async_set(False)

    async def async_update(self) -> None:
        """Refresh the state from the camera."""
        try:
            status = await self.hass.async_add_executor_job(
                self._client.get_deterrence_status
            )
        except ImouConnectionError:
            self._attr_available = False
            return
        self._attr_available = True
        self._attr_is_on = status.get("warning_light", self._attr_is_on)
