"""Local ONVIF and deterrence client for Imou cameras."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from onvif import ONVIFCamera
import requests
from requests.auth import HTTPDigestAuth


class ImouConnectionError(Exception):
    """Raised when the camera cannot be reached or authenticated."""


class ImouNoPtzProfileError(Exception):
    """Raised when no PTZ-capable media profile exists."""


@dataclass(frozen=True, slots=True)
class ImouPreset:
    """An ONVIF preset exposed by the camera."""

    name: str
    token: str


class ImouPtzClient:
    """Talk to an Imou camera using its local ONVIF endpoint."""

    def __init__(self, host: str, port: int, username: str, password: str) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password

    async def _connect(self) -> tuple[Any, Any, Any]:
        try:
            camera = ONVIFCamera(
                self.host, self.port, self.username, self.password
            )
            await camera.update_xaddrs()
            media = await camera.create_media_service()
            ptz = await camera.create_ptz_service()
            profiles = await media.GetProfiles()
        except Exception as err:
            if "camera" in locals():
                await camera.close()
            raise ImouConnectionError(str(err)) from err

        profile = next(
            (
                item
                for item in profiles
                if getattr(item, "PTZConfiguration", None) is not None
            ),
            None,
        )
        if profile is None:
            await camera.close()
            raise ImouNoPtzProfileError("No PTZ-capable ONVIF profile was found")
        return camera, ptz, profile

    async def get_presets(self) -> list[ImouPreset]:
        """Return every preset supplied by the selected PTZ profile."""
        camera, ptz, profile = await self._connect()
        try:
            result = await ptz.GetPresets({"ProfileToken": profile.token}) or []
        except Exception as err:
            raise ImouConnectionError(str(err)) from err
        finally:
            await camera.close()

        presets: list[ImouPreset] = []
        for index, item in enumerate(result, start=1):
            token = str(getattr(item, "token", "") or "")
            if not token:
                continue
            name = str(getattr(item, "Name", "") or "").strip()
            presets.append(ImouPreset(name=name or f"Preset {index}", token=token))
        return presets

    async def goto_preset(self, token: str) -> None:
        """Move the camera to an ONVIF preset token."""
        camera, ptz, profile = await self._connect()
        try:
            request = ptz.create_type("GotoPreset")
            request.ProfileToken = profile.token
            request.PresetToken = token
            await ptz.GotoPreset(request)
        except Exception as err:
            raise ImouConnectionError(str(err)) from err
        finally:
            await camera.close()

    def _cgi(self, path: str) -> str:
        """Call the Dahua-compatible local CGI endpoint used by Imou firmware."""
        try:
            response = requests.get(
                f"http://{self.host}:{self.port}{path}",
                auth=HTTPDigestAuth(self.username, self.password),
                timeout=10,
            )
            response.raise_for_status()
        except requests.RequestException as err:
            raise ImouConnectionError(str(err)) from err
        if "error" in response.text.lower():
            raise ImouConnectionError(response.text.strip())
        return response.text

    def get_deterrence_status(self) -> dict[str, bool]:
        """Return supported light/speaker states from compatible firmware."""
        text = self._cgi(
            "/cgi-bin/coaxialControlIO.cgi?action=getStatus&channel=1"
        )
        result: dict[str, bool] = {}
        for line in text.splitlines():
            key, separator, value = line.partition("=")
            if not separator:
                continue
            if key.endswith("WhiteLight"):
                result["warning_light"] = value.strip().lower() == "on"
            elif key.endswith("Speaker"):
                result["siren"] = value.strip().lower() == "on"
        return result

    def set_warning_light(self, enabled: bool) -> None:
        """Turn the camera deterrence/white-light output on or off."""
        value = 1 if enabled else 0
        self._cgi(
            "/cgi-bin/coaxialControlIO.cgi?action=control&channel=1&"
            f"info[0].Type=1&info[0].IO={value}"
        )

    def set_siren(self, enabled: bool) -> None:
        """Start or stop the camera's built-in deterrence sound."""
        value = 1 if enabled else 2
        self._cgi(
            "/cgi-bin/coaxialControlIO.cgi?action=control&channel=1&"
            f"info[0].Type=2&info[0].IO={value}"
        )
