# App5 — presets and spotlight MQTT bridge

Siren support has been removed. The working spotlight and preset features remain, along with the original Cameras, IMOU Cloud and MQTT settings tabs. The extra dashboard/video features are not included.

## Run the Windows executable

Double-click `ImouBridge.exe`. Python and pip are not needed; the executable includes its runtime, dependencies, Tk GUI and ONVIF WSDL files. Existing settings are loaded from your Windows user profile.

The packaged executable passed its offline GUI/import/WSDL self-test.

## Run from Python source (optional)

Extract the ZIP. Open PowerShell in that folder:

```powershell
$venv = "$env:LOCALAPPDATA\ImouApp5\.venv"
python -m venv "$venv"
& "$venv\Scripts\python.exe" -m pip install -r .\requirements-app5.txt
& "$venv\Scripts\python.exe" .\app5.py
```

If dependencies are already installed, only the last command is needed. Stop the old app before replacing app5.py. Start the new app. It automatically connects to the MQTT broker and publishes Home Assistant discovery when at least one camera is configured. Adding a camera also connects automatically, restarting an existing bridge to include the new camera. The Connect button remains available for manual retry, and Stop stops the connection. It will remove the old siren discovery entries for configured cameras automatically. No siren commands are sent.

Settings remain in `%APPDATA%\ImouPtzBridge\config-app5.json`; if absent, App4's config.json is read. Credentials are stored in plaintext as in App4. App4 is unchanged.

## Changes

- Redesigned three-tab interface with consistent spacing, readable form labels, a resizable camera table, scrollbars, a separate connection/status bar and a contrasting activity log.
- Automatic Home Assistant/MQTT connection on startup with saved cameras, and immediately after adding a camera.

- Siren methods, subscriptions, MQTT commands, discovery entities and related UI text removed. Only cleanup of previously published siren discovery records remains.
- Spotlight operation retained, including local control and the working cloud fallback with state confirmation.
- HTTP connections and digest authentication are reused.
- ONVIF camera, PTZ service and media profile are reused rather than re-created for each preset command. They are invalidated after an error so the next command reconnects.
- Once cloud spotlight access works, subsequent spotlight operations go directly to it rather than waiting on an unresponsive local CGI endpoint each time.
- Local CGI timeouts are shorter. A timed-out request is not repeated on another channel; failed local access is remembered for 120 seconds.
- All three connection-test buttons run in the background and report real results. MQTT waits for broker login acknowledgement. Cloud authentication success is distinguished from device permission.

## Verification

29 automated tests passed, including GUI success/failure button paths, MQTT rejection and timeout handling, siren removal/cleanup, connection reuse, spotlight routing, cloud authentication signing and automatic connection. All three tabs were also checked for control clipping at the default and minimum window sizes.

Live read-only timings on the configured camera during verification:

| Operation | Time |
| --- | ---: |
| ONVIF authentication | 0.760 s |
| First preset read | 0.212 s |
| Repeated preset read | 0.137 s |
| Initial spotlight read (including local timeout and cloud fallback) | 3.221 s |
| Repeated spotlight read | 0.064 s |

These are observed timings, not guaranteed response times. Spotlight status was checked without toggling the light. The camera, MQTT and cloud connection checks also passed live during the previous revision.
