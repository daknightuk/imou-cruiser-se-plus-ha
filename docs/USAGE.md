# Using Imou Cruiser SE Plus PTZ

## Before installation

1. Give the camera a fixed address using a DHCP reservation in your router.
2. Enable ONVIF in the camera settings.
3. Create an ONVIF/device user if your firmware requires one. This may be
   different from your Imou Life account.
4. Create and name your PTZ presets in the camera app or another ONVIF tool.
5. Confirm that Home Assistant can reach the camera IP on the local network.

## Install with HACS

1. Open **HACS → Integrations**.
2. Open the three-dot menu and select **Custom repositories**.
3. Enter this GitHub repository URL.
4. Select **Integration** as the category and add it.
5. Find **Imou Cruiser SE Plus PTZ** in HACS and select **Download**.
6. Restart Home Assistant.

## Install manually

1. Download the latest release or repository ZIP.
2. Copy the folder `custom_components/imou_cruiser_se_plus` to:
   `/config/custom_components/imou_cruiser_se_plus`.
3. Restart Home Assistant.

The final path must contain `manifest.json` directly inside the
`imou_cruiser_se_plus` folder. Avoid accidentally creating a duplicate nested
folder.

## Add a camera

1. Open **Settings → Devices & services**.
2. Select **Add integration**.
3. Search for **Imou Cruiser SE Plus PTZ**.
4. Enter:
   - **Camera IP address:** for example, `192.168.1.37`.
   - **ONVIF port:** normally `80`.
   - **Username:** commonly `admin`, or your ONVIF/device user.
   - **Password:** the password for that local camera user.
5. Submit the form. The integration verifies the connection and discovers the
   presets before completing setup.

## Entities created

The exact entities depend on the camera firmware:

- One button for every named ONVIF preset.
- **Trigger siren** and **Stop siren** buttons when the speaker deterrence API
  is reported by the camera.
- A **Warning light** switch when the compatible light API is reported.

The preset name from the camera becomes the button name. If a preset has no
name, it is shown as `Preset 1`, `Preset 2`, and so on.

## Add controls to a dashboard

Open a dashboard, select **Edit dashboard → Add card → Entities**, then add the
preset buttons, warning-light switch and siren buttons from the Imou camera
device. A Tile card also works well for an individual preset or switch.

## Use a preset in an automation

Choose the **Button: Press** action in Home Assistant's automation editor and
select the required preset button. A YAML action has this form:

```yaml
action:
  - action: button.press
    target:
      entity_id: button.imou_cruiser_se_plus_door
```

Use the entity picker rather than copying the example entity ID, because Home
Assistant generates the ID from your camera and preset name.

## Trigger deterrence from Frigate

The siren and light are ordinary Home Assistant entities, so they can be used
in a Frigate event automation. For safety, include a delay and an off/stop
action so the deterrence does not remain active:

```yaml
action:
  - action: switch.turn_on
    target:
      entity_id: switch.imou_cruiser_se_plus_warning_light
  - action: button.press
    target:
      entity_id: button.imou_cruiser_se_plus_trigger_siren
  - delay: "00:00:10"
  - action: button.press
    target:
      entity_id: button.imou_cruiser_se_plus_stop_siren
  - action: switch.turn_off
    target:
      entity_id: switch.imou_cruiser_se_plus_warning_light
```

Select your actual entities in the visual automation editor. Test the siren
during a suitable daytime period before using it in an automatic alert.

## Add or rename presets later

Create or rename the preset on the camera, then open **Settings → Devices &
services**, find the integration and select **Reload**. The integration
discovers presets when its entities are set up.

## Troubleshooting

### Cannot connect

- Check the camera IP and ONVIF port.
- Confirm ONVIF is enabled.
- Try the local ONVIF/device credentials instead of the Imou Life password.
- Confirm the camera and Home Assistant can communicate across any VLAN or
  firewall rules.

### Preset buttons are missing

- Create at least one preset on the camera.
- Confirm the chosen media profile supports PTZ.
- Reload the integration after changing presets.

### Presets work but light or siren controls are absent

ONVIF presets and deterrence controls use different local interfaces. Some Imou
firmware exposes ONVIF PTZ but removes the Dahua-compatible light/speaker API.
The integration deliberately omits controls it cannot detect.

### The camera returns success but the light does not change

Some firmware accepts a compatible command without operating the hardware. The
integration cannot safely infer success from that response. Check for camera
firmware updates and test the corresponding control in the Imou app.
