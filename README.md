# Imou Cruiser SE Plus PTZ for Home Assistant

A local-only Home Assistant custom integration for Imou Cruiser SE Plus cameras.
It connects directly to the camera over ONVIF and automatically imports every
camera preset as a Home Assistant button. No MQTT broker or cloud account is
required.

## Why this integration exists

The Imou Cruiser SE Plus exposes its saved PTZ presets through ONVIF, but Home
Assistant's standard ONVIF integration does not import those named presets as
individual button entities. This makes the presets awkward to use in dashboards
and automations even though the camera itself supports them.

This dedicated integration reads the missing preset information through ONVIF
and creates native Home Assistant entities. It stores credentials in the Home
Assistant config entry and also exposes compatible local deterrence controls
for the camera light and siren.

## Features

- UI setup asks for camera IP, ONVIF port, username and password.
- Validates the connection during setup.
- Discovers the camera's named ONVIF presets.
- Creates one button entity per preset.
- Adds **Trigger siren** and **Stop siren** buttons on compatible firmware.
- Adds a **Warning light** switch on compatible firmware.
- Supports multiple cameras as separate integration entries.
- Sends credentials only to the camera on the local network.

## Camera preparation

In the Imou camera settings, enable ONVIF and create an ONVIF/device user if
required by your firmware. Create and name the PTZ presets before adding the
integration.

## Manual installation

1. Copy `custom_components/imou_cruiser_se_plus` into Home Assistant's
   `/config/custom_components/` directory.
2. Restart Home Assistant.
3. Open **Settings → Devices & services → Add integration**.
4. Search for **Imou Cruiser SE Plus PTZ**.
5. Enter the camera IP, ONVIF port (normally `80`), username and password.

The discovered presets appear as buttons beneath the camera device. To import
presets added later, reload the integration entry.

The deterrence controls use the camera's local Dahua-compatible CGI interface.
They are only created when the camera reports the matching light or speaker
capability. Firmware support varies, so preset buttons may still work even when
the siren or light controls are unavailable.

## HACS

Add this repository to HACS as a custom repository of type **Integration**, then
download **Imou Cruiser SE Plus PTZ** and restart Home Assistant.

See [Using the integration](docs/USAGE.md) for detailed installation,
dashboard and automation examples. See [How it works](docs/HOW_IT_WORKS.md) for
the design, supported local interfaces and firmware limitations.

## Troubleshooting

- Confirm Home Assistant can reach the camera IP and ONVIF port.
- Use the camera's ONVIF/device credentials, which may differ from the Imou Life
  account password.
- Ensure at least one preset exists in the camera before setup.
- A fixed DHCP reservation is recommended so the camera IP does not change.

This is a community project and is not affiliated with Imou or Dahua.
