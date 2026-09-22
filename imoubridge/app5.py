from __future__ import annotations

import asyncio
import hashlib
import json
import os
import queue
import re
import socket
import threading
import time
import tkinter as tk
import uuid
import webbrowser
from dataclasses import asdict, dataclass, field
from tkinter import font as tkfont
from tkinter import messagebox, ttk
from typing import Optional

import paho.mqtt.client as mqtt
import requests
from onvif import ONVIFCamera
import onvif
from requests.auth import HTTPDigestAuth

APP_NAME = "Imou PTZ MQTT Bridge — App5"
CONFIG_DIR = os.path.join(
    os.environ.get("APPDATA") or os.path.expanduser("~"), "ImouPtzBridge"
)
CONFIG_PATH = os.path.join(CONFIG_DIR, "config-app5.json")
STATE_TOPIC_PREFIX = "imou_ptz_bridge"

CLOUD_URLS = {
    "sg": "https://openapi-sg.easy4ip.com/openapi",
    "eu": "https://openapi-fk.easy4ip.com/openapi",
    "na": "https://openapi-or.easy4ip.com/openapi",
    "cn": "https://openapi.lechange.cn/openapi",
}


def slugify(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_]+", "_", value.strip().lower())
    return re.sub(r"_+", "_", value).strip("_") or "camera"


# --------------------------------------------------------------------------
# Imou Cloud API Client
# --------------------------------------------------------------------------

class ImouCloudClient:
    """Client for interacting with Imou Open Platform Cloud API."""

    def __init__(self, app_id: str, app_secret: str, region: str = "eu"):
        self.app_id = app_id.strip()
        self.app_secret = app_secret.strip()
        self.base_url = CLOUD_URLS.get(region, CLOUD_URLS["eu"])
        self._access_token: Optional[str] = None
        self._token_expires: float = 0.0







# --------------------------------------------------------------------------
# Camera Client
# --------------------------------------------------------------------------

class CameraError(Exception):
    pass


class CameraClient:
    """Talk to one camera over ONVIF (presets) and local CGI / Cloud (spotlight)."""

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        cloud_client: Optional[ImouCloudClient] = None,
        cloud_device_id: str = "",
        cloud_channel_id: str = "0",
    ):
        self.host = host
        self.port = int(port)
        self.username = username
        self.password = password
        self.cloud_client = cloud_client
        self.cloud_device_id = cloud_device_id
        self.cloud_channel_id = cloud_channel_id


    def _sync_connect_and_get_presets(self) -> list[dict]:
        camera = self._create_onvif_camera()
        try:
            media = camera.create_media_service()
            ptz = camera.create_ptz_service()
            profiles = media.GetProfiles()

            profile = next(
                (p for p in profiles if getattr(p, "PTZConfiguration", None) is not None),
                None,
            )
            if profile is None:
                raise CameraError("No PTZ-capable ONVIF profile found")

            result = ptz.GetPresets({"ProfileToken": profile.token}) or []

            presets = []
            for index, item in enumerate(result, start=1):
                token = str(getattr(item, "token", "") or "")
                if not token:
                    continue
                name = str(getattr(item, "Name", "") or "").strip() or f"Preset {index}"
                presets.append({"name": name, "token": token})
            return presets

        except Exception as err:
            raise CameraError(f"ONVIF preset fetch failed: {err}") from err
        finally:
            if hasattr(camera, "close"):
                try:
                    camera.close()
                except Exception:
                    pass

    async def _async_get_presets(self) -> list[dict]:
        return await asyncio.to_thread(self._sync_connect_and_get_presets)

    def get_presets(self) -> list[dict]:
        return asyncio.run(self._async_get_presets())

    def _sync_test_connection(self) -> None:
        camera = self._create_onvif_camera()
        try:
            media = camera.create_media_service()
            media.GetProfiles()
        finally:
            if hasattr(camera, "close"):
                try:
                    camera.close()
                except Exception:
                    pass

    async def _async_test_connection(self) -> None:
        await asyncio.to_thread(self._sync_test_connection)


    def _sync_goto_preset(self, token: str) -> None:
        camera = self._create_onvif_camera()
        try:
            media = camera.create_media_service()
            ptz = camera.create_ptz_service()
            profiles = media.GetProfiles()

            profile = next(
                (p for p in profiles if getattr(p, "PTZConfiguration", None) is not None),
                None,
            )
            if profile is None:
                raise CameraError("No PTZ-capable ONVIF profile found")

            request = ptz.create_type("GotoPreset")
            request.ProfileToken = profile.token
            request.PresetToken = token
            ptz.GotoPreset(request)
        except Exception as err:
            raise CameraError(f"GotoPreset failed: {err}") from err
        finally:
            if hasattr(camera, "close"):
                try:
                    camera.close()
                except Exception:
                    pass

    async def _async_goto_preset(self, token: str) -> None:
        await asyncio.to_thread(self._sync_goto_preset, token)

    def goto_preset(self, token: str) -> None:
        asyncio.run(self._async_goto_preset(token))






# --------------------------------------------------------------------------
# Config Data Models
# --------------------------------------------------------------------------

@dataclass
class CameraConfig:
    name: str
    host: str
    port: int = 80
    username: str = "admin"
    password: str = ""
    cloud_device_id: str = ""
    cloud_channel_id: str = "0"

    @property
    def device_id(self) -> str:
        return slugify(f"{self.name}_{self.host}")


@dataclass
class ImouCloudConfig:
    app_id: str = ""
    app_secret: str = ""
    region: str = "eu"


@dataclass
class MqttConfig:
    host: str = "localhost"
    port: int = 1883
    username: str = ""
    password: str = ""
    discovery_prefix: str = "homeassistant"


@dataclass
class AppConfig:
    mqtt: MqttConfig = field(default_factory=MqttConfig)
    imou_cloud: ImouCloudConfig = field(default_factory=ImouCloudConfig)
    cameras: list = field(default_factory=list)

    def save(self):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        data = {
            "mqtt": asdict(self.mqtt),
            "imou_cloud": asdict(self.imou_cloud),
            "cameras": [asdict(c) for c in self.cameras],
        }
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    @classmethod
    def load(cls) -> "AppConfig":
        path = CONFIG_PATH
        if not os.path.exists(path):
            path = os.path.join(CONFIG_DIR, "config.json")
        if not os.path.exists(path):
            return cls()
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            mqtt_cfg = MqttConfig(**data.get("mqtt", {}))
            cloud_cfg = ImouCloudConfig(**data.get("imou_cloud", {}))
            cameras = [CameraConfig(**c) for c in data.get("cameras", [])]
            return cls(mqtt=mqtt_cfg, imou_cloud=cloud_cfg, cameras=cameras)
        except Exception:
            return cls()


# --------------------------------------------------------------------------
# MQTT Bridge Service
# --------------------------------------------------------------------------

class Bridge:
    def __init__(self, config: AppConfig, log_fn):
        self.config = config
        self.log = log_fn
        self.client: Optional[mqtt.Client] = None
        self._running = False
        self._camera_clients: dict[str, CameraClient] = {}
        self._presets: dict[str, list[dict]] = {}
        self._deterrence: dict[str, dict] = {}
        self.cloud_client: Optional[ImouCloudClient] = None
        self.cloud_connected = False

        if config.imou_cloud.app_id and config.imou_cloud.app_secret:
            self.cloud_client = ImouCloudClient(
                config.imou_cloud.app_id,
                config.imou_cloud.app_secret,
                config.imou_cloud.region,
            )

    def start(self):
        if self._running:
            return
        self._running = True
        threading.Thread(target=self._run, daemon=True).start()


    def _run(self):
        mqtt_cfg = self.config.mqtt
        client_id = f"imou_ptz_bridge_{int(time.time())}"
        self.client = mqtt.Client(
            client_id=client_id, callback_api_version=mqtt.CallbackAPIVersion.VERSION2
        )
        if mqtt_cfg.username:
            self.client.username_pw_set(mqtt_cfg.username, mqtt_cfg.password)

        self.client.connect_timeout = 8
        self.client.will_set(f"{STATE_TOPIC_PREFIX}/bridge/status", "offline", retain=True)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect

        try:
            self.client.connect(mqtt_cfg.host, int(mqtt_cfg.port), keepalive=30)
        except Exception as err:
            self.log(f"[error] Could not connect to MQTT broker: {err}")
            self._running = False
            return

        self.client.loop_start()

        if self.cloud_client:
            try:
                self.cloud_client.get_access_token()
                self.cloud_connected = True
                self.log("[cloud] Authenticated with IMOU Cloud API successfully.")
            except Exception as err:
                self.log(f"[cloud] Auth failed: {err}")
                self.cloud_connected = False

        for cam_cfg in self.config.cameras:
            if not self._running:
                break
            self._setup_camera(cam_cfg)

        while self._running:
            time.sleep(0.5)

        self.client.loop_stop()


    def _device_block(self, cam_cfg: CameraConfig) -> dict:
        return {
            "identifiers": [cam_cfg.device_id],
            "name": cam_cfg.name,
            "manufacturer": "Imou",
            "model": "PTZ camera (via ONVIF bridge)",
            "configuration_url": f"http://{cam_cfg.host}",
        }

    def _availability_topic(self, cam_cfg: CameraConfig) -> str:
        return f"{STATE_TOPIC_PREFIX}/{cam_cfg.device_id}/status"

    def _publish_discovery(self, cam_cfg: CameraConfig, presets: list[dict], deterrence: dict):
        prefix = self.config.mqtt.discovery_prefix
        device = self._device_block(cam_cfg)
        availability_topic = self._availability_topic(cam_cfg)

        for preset in presets:
            object_id = f"{cam_cfg.device_id}_{slugify(preset['token'])}"
            command_topic = (
                f"{STATE_TOPIC_PREFIX}/{cam_cfg.device_id}/preset/{preset['token']}/set"
            )
            payload = {
                "name": preset["name"],
                "unique_id": object_id,
                "command_topic": command_topic,
                "payload_press": "PRESS",
                "availability": [{"topic": availability_topic}, {"topic": f"{STATE_TOPIC_PREFIX}/bridge/status"}],
                "availability_mode": "all",
                "device": device,
                "icon": "mdi:camera-control",
            }
            self.client.publish(
                f"{prefix}/button/{object_id}/config", json.dumps(payload), retain=True
            )

        if "warning_light" in deterrence:
            object_id = f"{cam_cfg.device_id}_light"
            command_topic = f"{STATE_TOPIC_PREFIX}/{cam_cfg.device_id}/light/set"
            state_topic = f"{STATE_TOPIC_PREFIX}/{cam_cfg.device_id}/light/state"
            payload = {
                "name": "Warning light",
                "unique_id": object_id,
                "command_topic": command_topic,
                "state_topic": state_topic,
                "payload_on": "ON",
                "payload_off": "OFF",
                "state_on": "ON",
                "state_off": "OFF",
                "availability": [{"topic": availability_topic}, {"topic": f"{STATE_TOPIC_PREFIX}/bridge/status"}],
                "availability_mode": "all",
                "device": device,
                "icon": "mdi:spotlight-beam",
            }
            self.client.publish(
                f"{prefix}/switch/{object_id}/config", json.dumps(payload), retain=True
            )


        self.client.subscribe(f"{STATE_TOPIC_PREFIX}/{cam_cfg.device_id}/preset/+/set")
        self.client.subscribe(f"{STATE_TOPIC_PREFIX}/{cam_cfg.device_id}/light/set")

    def _publish_availability(self, cam_cfg: CameraConfig, state: str):
        if self.client is not None:
            self.client.publish(self._availability_topic(cam_cfg), state, retain=True)

    def _publish_all_availability(self, state: str):
        for cam_cfg in self.config.cameras:
            self._publish_availability(cam_cfg, state)

    def _publish_light_state(self, cam_cfg: CameraConfig, on: bool):
        topic = f"{STATE_TOPIC_PREFIX}/{cam_cfg.device_id}/light/state"
        self.client.publish(topic, "ON" if on else "OFF", retain=True)

    # -- MQTT Callbacks --------------------------------------------------






# --------------------------------------------------------------------------
# GUI Dialogs & Main Window
# --------------------------------------------------------------------------

class CameraDialog(tk.Toplevel):
    def __init__(self, parent, existing: Optional[CameraConfig] = None):
        super().__init__(parent)
        self.title("Camera Settings")
        self.resizable(False, False)
        self.result: Optional[CameraConfig] = None

        # Section 1: Local Settings
        local_frame = ttk.LabelFrame(self, text="Local Settings")
        local_frame.pack(fill="x", padx=10, pady=6)

        ttk.Label(local_frame, text="Name").grid(row=0, column=0, sticky="w", padx=8, pady=4)
        self.name_var = tk.StringVar(value=existing.name if existing else "")
        ttk.Entry(local_frame, textvariable=self.name_var, width=30).grid(row=0, column=1, padx=8, pady=4)

        ttk.Label(local_frame, text="Camera IP address").grid(row=1, column=0, sticky="w", padx=8, pady=4)
        self.host_var = tk.StringVar(value=existing.host if existing else "")
        ttk.Entry(local_frame, textvariable=self.host_var, width=30).grid(row=1, column=1, padx=8, pady=4)

        ttk.Label(local_frame, text="ONVIF port").grid(row=2, column=0, sticky="w", padx=8, pady=4)
        self.port_var = tk.StringVar(value=str(existing.port) if existing else "80")
        ttk.Entry(local_frame, textvariable=self.port_var, width=30).grid(row=2, column=1, padx=8, pady=4)

        ttk.Label(local_frame, text="Username").grid(row=3, column=0, sticky="w", padx=8, pady=4)
        self.username_var = tk.StringVar(value=existing.username if existing else "admin")
        ttk.Entry(local_frame, textvariable=self.username_var, width=30).grid(row=3, column=1, padx=8, pady=4)

        ttk.Label(local_frame, text="Password").grid(row=4, column=0, sticky="w", padx=8, pady=4)
        self.password_var = tk.StringVar(value=existing.password if existing else "")
        ttk.Entry(local_frame, textvariable=self.password_var, width=30, show="*").grid(row=4, column=1, padx=8, pady=4)

        # Section 2: Cloud Service
        cloud_frame = ttk.LabelFrame(self, text="Cloud Service")
        cloud_frame.pack(fill="x", padx=10, pady=6)

        ttk.Label(cloud_frame, text="Device Serial").grid(row=0, column=0, sticky="w", padx=8, pady=4)
        self.cloud_device_id_var = tk.StringVar(value=existing.cloud_device_id if existing else "")
        ttk.Entry(cloud_frame, textvariable=self.cloud_device_id_var, width=30).grid(row=0, column=1, padx=8, pady=4)

        ttk.Label(cloud_frame, text="Channel ID").grid(row=1, column=0, sticky="w", padx=8, pady=4)
        self.cloud_channel_id_var = tk.StringVar(value=existing.cloud_channel_id if existing else "0")
        ttk.Entry(cloud_frame, textvariable=self.cloud_channel_id_var, width=30).grid(row=1, column=1, padx=8, pady=4)

        # Action Buttons
        button_frame = ttk.Frame(self)
        button_frame.pack(pady=10)
        ttk.Button(button_frame, text="Save", command=self._on_save).pack(side="left", padx=5)
        ttk.Button(button_frame, text="Cancel", command=self.destroy).pack(side="left", padx=5)

        self.grab_set()



class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1120x840")
        self.minsize(940, 800)

        self.config_data = AppConfig.load()
        self.bridge: Optional[Bridge] = None
        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.status_queue: "queue.Queue[tuple[str, Optional[bool]]]" = queue.Queue()
        self.camera_status: dict[str, Optional[bool]] = {}
        self.show_passwords_var = tk.BooleanVar(value=False)

        self._build_ui()
        self._refresh_camera_list()
        self.after(200, self._drain_log_queue)
        self.after(200, self._drain_status_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        for cam in self.config_data.cameras:
            self._test_camera_async(cam)



    # -- UI Construction --------------------------------------------------

    def _build_ui(self):
        style = ttk.Style(self)
        style.theme_use('clam')
        self.configure(background='#eef2f7')
        style.configure('.',font=('Segoe UI',10),background='#eef2f7',foreground='#172b45')
        style.configure('TButton',padding=(13,8))
        style.configure('Accent.TButton',background='#2469c9',foreground='white')
        style.map('Accent.TButton',background=[('active','#1c55a5'),('disabled','#b9c7d8')])
        style.configure('TNotebook',background='#eef2f7',borderwidth=0)
        style.configure('TNotebook.Tab',padding=(22,11))
        style.map('TNotebook.Tab',background=[('selected','#ffffff')],foreground=[('selected','#1856a6')])
        style.configure('Card.TFrame',background='#ffffff')
        style.configure('Card.TLabel',background='#ffffff')
        style.configure('Muted.TLabel',foreground='#61738a')
        style.configure('Title.TLabel',font=('Segoe UI',22,'bold'))
        style.configure('Heading.TLabel',font=('Segoe UI',13,'bold'),background='#ffffff')
        style.configure('Treeview',rowheight=34,font=('Segoe UI',10),background='white',fieldbackground='white',borderwidth=0)
        style.configure('Treeview.Heading',font=('Segoe UI',10,'bold'),padding=(8,10),background='#e6edf5')
        style.map('Treeview',background=[('selected','#d8e9ff')],foreground=[('selected','#143c70')])
        style.configure('TEntry',padding=7,fieldbackground='white')
        style.configure('TCombobox',padding=6)
        self.columnconfigure(0,weight=1)
        self.rowconfigure(1,weight=1)

        header=ttk.Frame(self,padding=(22,16,22,12))
        header.grid(row=0,column=0,sticky='ew')
        ttk.Label(header,text='IMOU  /  Camera Bridge',style='Title.TLabel').pack(anchor='w')
        ttk.Label(header,text='Presets & spotlight  •  Home Assistant via MQTT  •  Auto-connect when cameras are configured',style='Muted.TLabel').pack(anchor='w',pady=(4,0))

        notebook=ttk.Notebook(self)
        notebook.grid(row=1,column=0,sticky='nsew',padx=20)
        cameras_tab=ttk.Frame(notebook,padding=16,style='Card.TFrame')
        cloud_tab=ttk.Frame(notebook,padding=22,style='Card.TFrame')
        mqtt_tab=ttk.Frame(notebook,padding=22,style='Card.TFrame')
        notebook.add(cameras_tab,text='Cameras')
        notebook.add(cloud_tab,text='IMOU Cloud')
        notebook.add(mqtt_tab,text='MQTT settings')

        cameras_tab.columnconfigure(0,weight=1)
        cameras_tab.rowconfigure(2,weight=1)
        ttk.Label(cameras_tab,text='Your cameras',style='Heading.TLabel').grid(row=0,column=0,sticky='w')
        ttk.Label(cameras_tab,text='Select a camera to edit its settings or test the local connection.',style='Card.TLabel').grid(row=1,column=0,sticky='w',pady=(4,12))
        table=ttk.Frame(cameras_tab,style='Card.TFrame')
        table.grid(row=2,column=0,sticky='nsew')
        table.columnconfigure(0,weight=1);table.rowconfigure(0,weight=1)
        columns=('status','name','host','port','username','password')
        self.tree=ttk.Treeview(table,columns=columns,show='headings',selectmode='browse',height=6)
        headings=('Connection','Camera name','IP / hostname','Port','Username','Password')
        for col,label in zip(columns,headings):
            self.tree.heading(col,text=label)
            self.tree.column(col,anchor='w',stretch=col in ('name','host','password'))
        self.tree.column('status',anchor='center')
        for tag,color in [('ok','#26704b'),('fail','#b63535'),('pending','#966714')]:
            self.tree.tag_configure(tag,foreground=color)
        self.tree.grid(row=0,column=0,sticky='nsew')
        vertical=ttk.Scrollbar(table,orient='vertical',command=self.tree.yview)
        vertical.grid(row=0,column=1,sticky='ns')
        horizontal=ttk.Scrollbar(table,orient='horizontal',command=self.tree.xview)
        horizontal.grid(row=1,column=0,sticky='ew')
        self.tree.configure(yscrollcommand=vertical.set,xscrollcommand=horizontal.set)
        self._col_font=tkfont.nametofont('TkDefaultFont')
        toolbar=ttk.Frame(cameras_tab,style='Card.TFrame')
        toolbar.grid(row=3,column=0,sticky='ew',pady=(12,0))
        for text,command in [('Add camera',self._add_camera),('Edit selected',self._edit_camera),('Remove selected',self._remove_camera),('Re-test connection',self._retest_selected)]:
            ttk.Button(toolbar,text=text,command=command,style='Accent.TButton' if text=='Add camera' else 'TButton').pack(side='left',padx=(0,8))
        ttk.Checkbutton(cameras_tab,text='Show passwords',variable=self.show_passwords_var,command=self._refresh_camera_list).grid(row=4,column=0,sticky='w',pady=(10,0))

        self.cloud_vars={key:tk.StringVar(value=getattr(self.config_data.imou_cloud,key)) for key in ('app_id','app_secret','region')}
        self.mqtt_vars={key:tk.StringVar(value=str(getattr(self.config_data.mqtt,key))) for key in ('host','port','username','discovery_prefix')}
        self.mqtt_password_var=tk.StringVar(value=self.config_data.mqtt.password)

        def form(page,title,subtitle):
            page.columnconfigure(0,weight=1)
            ttk.Label(page,text=title,style='Heading.TLabel').grid(row=0,column=0,sticky='w')
            ttk.Label(page,text=subtitle,style='Card.TLabel',wraplength=790).grid(row=1,column=0,sticky='w',pady=(5,18))
            fields=ttk.Frame(page,style='Card.TFrame')
            fields.grid(row=2,column=0,sticky='nw')
            fields.columnconfigure(1,weight=1)
            return fields

        cloud_fields=form(cloud_tab,'Cloud connection','Optional spotlight fallback. Use your Imou Open Platform application credentials and its data-center region.')
        for row,(label,key) in enumerate([('App ID','app_id'),('App Secret','app_secret'),('Server Region','region')]):
            ttk.Label(cloud_fields,text=label,style='Card.TLabel').grid(row=row,column=0,sticky='w',padx=(0,24),pady=7)
            if key=='region':
                entry=ttk.Combobox(cloud_fields,textvariable=self.cloud_vars[key],values=['eu','sg','na','cn'],state='readonly',width=42)
            else:
                entry=ttk.Entry(cloud_fields,textvariable=self.cloud_vars[key],width=44,show='*' if key=='app_secret' else '')
            entry.grid(row=row,column=1,sticky='ew',pady=7)
        ttk.Button(cloud_fields,text='Test Cloud Connection',command=self._test_cloud_connection).grid(row=3,column=1,sticky='w',pady=(12,0))
        ttk.Label(cloud_tab,text='This test checks application login. Device authorization is separate.',style='Card.TLabel').grid(row=3,column=0,sticky='w',pady=(18,5))
        link=ttk.Label(cloud_tab,text='Open Imou developer portal ↗',style='Card.TLabel',foreground='#2469c9',cursor='hand2')
        link.grid(row=4,column=0,sticky='w')
        link.bind('<Button-1>',lambda e:webbrowser.open_new('https://open.imoulife.com'))

        mqtt_fields=form(mqtt_tab,'Home Assistant connection','Use the same MQTT broker as Home Assistant. The bridge connects automatically when one or more cameras are configured.')
        for row,(label,var,secret) in enumerate([
            ('Broker host',self.mqtt_vars['host'],False),('Broker port',self.mqtt_vars['port'],False),
            ('Username (optional)',self.mqtt_vars['username'],False),('Password (optional)',self.mqtt_password_var,True),
            ('Discovery prefix',self.mqtt_vars['discovery_prefix'],False)]):
            ttk.Label(mqtt_fields,text=label,style='Card.TLabel').grid(row=row,column=0,sticky='w',padx=(0,24),pady=5)
            ttk.Entry(mqtt_fields,textvariable=var,width=44,show='*' if secret else '').grid(row=row,column=1,sticky='ew',pady=5)
        ttk.Button(mqtt_fields,text='Test MQTT Connection',command=self._test_mqtt_connection).grid(row=5,column=1,sticky='w',pady=(12,0))

        bottom=ttk.Frame(self,padding=(20,13))
        bottom.grid(row=2,column=0,sticky='ew')
        self.start_button=ttk.Button(bottom,text='Connect & publish to Home Assistant',command=self._start,style='Accent.TButton')
        self.start_button.pack(side='left')
        self.stop_button=ttk.Button(bottom,text='Stop',command=self._stop,state='disabled')
        self.stop_button.pack(side='left',padx=8)
        self.status_label=ttk.Label(bottom,text='Not connected',foreground='#61738a')
        self.status_label.pack(side='right',padx=8)

        log_frame=ttk.Frame(self,padding=(20,0,20,16))
        log_frame.grid(row=3,column=0,sticky='ew')
        log_frame.columnconfigure(0,weight=1)
        ttk.Label(log_frame,text='Activity',font=('Segoe UI',10,'bold')).grid(row=0,column=0,sticky='w',pady=(0,6))
        self.log_text=tk.Text(log_frame,height=5,state='disabled',wrap='word',font=('Consolas',9),background='#17283e',foreground='#d8e4f2',relief='flat',padx=12,pady=10)
        self.log_text.grid(row=1,column=0,sticky='ew')
        log_scroll=ttk.Scrollbar(log_frame,orient='vertical',command=self.log_text.yview)
        log_scroll.grid(row=1,column=1,sticky='ns')
        self.log_text.configure(yscrollcommand=log_scroll.set)

    def _autosize_columns(self):
        for name,width in [('status',105),('name',190),('host',170),('port',65),('username',120),('password',140)]:
            self.tree.column(name,width=width,minwidth=60 if name=='port' else 100)


    # -- Test Helpers -----------------------------------------------------



    # -- Camera List Management -------------------------------------------

    def _status_display(self, device_id: str) -> tuple[str, str]:
        status = self.camera_status.get(device_id, "unknown")
        if status is True:
            return "\u2714", "ok"
        if status is False:
            return "\u2716", "fail"
        if status is None:
            return "\u2026", "pending"
        return "?", "pending"



    def _add_camera(self):
        dialog = CameraDialog(self)
        self.wait_window(dialog)
        if dialog.result:
            self.config_data.cameras.append(dialog.result)
            self.config_data.save()
            self._refresh_camera_list()
            self._test_camera_async(dialog.result)

    def _selected_camera(self) -> Optional[CameraConfig]:
        selection = self.tree.selection()
        if not selection:
            return None
        device_id = selection[0]
        return next((c for c in self.config_data.cameras if c.device_id == device_id), None)

    def _edit_camera(self):
        cam = self._selected_camera()
        if cam is None:
            messagebox.showinfo(APP_NAME, "Select a camera first.")
            return
        dialog = CameraDialog(self, existing=cam)
        self.wait_window(dialog)
        if dialog.result:
            idx = self.config_data.cameras.index(cam)
            self.config_data.cameras[idx] = dialog.result
            self.config_data.save()
            self.camera_status.pop(cam.device_id, None)
            self._refresh_camera_list()
            self._test_camera_async(dialog.result)

    def _remove_camera(self):
        cam = self._selected_camera()
        if cam is None:
            messagebox.showinfo(APP_NAME, "Select a camera first.")
            return
        if messagebox.askyesno(APP_NAME, f"Remove '{cam.name}'?"):
            self.config_data.cameras.remove(cam)
            self.config_data.save()
            self.camera_status.pop(cam.device_id, None)
            self._refresh_camera_list()


    # -- Connection Testing -----------------------------------------------


    def _drain_status_queue(self):
        try:
            while True:
                device_id, ok = self.status_queue.get_nowait()
                self.camera_status[device_id] = ok
                self._refresh_camera_list()
        except queue.Empty:
            pass
        self.after(200, self._drain_status_queue)

    # -- Bridge Control ---------------------------------------------------



    def _stop(self):
        if self.bridge is not None:
            self.bridge.stop()
            self.bridge = None
        self.start_button.config(state="normal")
        self.stop_button.config(state="disabled")
        self.status_label.config(text="Not connected", foreground="#888")
        self._log("Bridge stopped.")


    # -- Logging ----------------------------------------------------------

    def _log(self, message: str):
        self.log_queue.put(message)

    def _drain_log_queue(self):
        try:
            while True:
                message = self.log_queue.get_nowait()
                self.log_text.config(state="normal")
                self.log_text.insert("end", message + "\n")
                self.log_text.see("end")
                self.log_text.config(state="disabled")
        except queue.Empty:
            pass
        self.after(200, self._drain_log_queue)



# App5 keeps the original three-tab bridge and corrects connection/control handling.
import base64
import copy
import hmac
from pathlib import Path
from zeep.transports import Transport
from urllib.parse import urlsplit


def safe_error(error):
    if isinstance(error, CameraError):
        return str(error)
    if isinstance(error, (requests.Timeout, TimeoutError, socket.timeout)):
        return 'Connection timed out. Check the address, port and local network.'
    if isinstance(error, requests.ConnectionError):
        return 'Cannot reach the server. Check the address, port and local network.'
    # SOAP/transport exception strings can contain credentials; do not display them.
    return f'{type(error).__name__}: check credentials, address/port and service support.'


class ImouCloudClient(ImouCloudClient):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._session = requests.Session()
        self._request_lock = threading.RLock()

    def _get_sign(self, time_int, nonce):
        key = hashlib.sha256(self.app_secret.encode()).hexdigest().encode()
        message = f'time:{time_int},nonce:{nonce},appSecret:{self.app_secret}'.encode()
        return base64.b64encode(hmac.new(key,message,hashlib.sha256).digest()).decode()

    def _request(self, method, params):
        now,nonce = int(time.time()),str(uuid.uuid4())
        body = {'system':{'ver':'1.0','appId':self.app_id,'sign':self._get_sign(now,nonce),'time':now,'nonce':nonce},'id':str(uuid.uuid4()),'params':params}
        try:
            with self._request_lock:
                response = self._session.post(f'{self.base_url}/{method}',json=body,timeout=(3,8))
            response.raise_for_status()
            result = response.json()['result']
        except requests.HTTPError as exc:
            raise CameraError(f'Cloud HTTP {exc.response.status_code}. Check data-center region and service access.') from None
        except (KeyError, ValueError):
            raise CameraError('Cloud returned an invalid response.') from None
        return result

    @staticmethod
    def _check(result):
        code = str(result.get('code','missing'))
        if code != '0':
            if code == 'OP1009':
                raise CameraError('OP1009: this Open Platform account is not authorized for the device. Check the device serial, data-center region and device binding. Local control is independent of this permission.')
            raise CameraError(f'Imou API error {code}. Check the application credentials, region and account permissions.')
        return result.get('data') or {}

    def get_access_token(self):
        if self._access_token and time.time() < self._token_expires:
            return self._access_token
        if not self.app_id or not self.app_secret:
            raise CameraError('App ID and App Secret are required.')
        data = self._check(self._request('accessToken',{}))
        token = data.get('accessToken')
        if not isinstance(token,str) or not token:
            raise CameraError('Cloud authentication returned no access token.')
        self._access_token = token
        self._token_expires = time.time()+max(0,float(data.get('expireTime',3600))-60)
        return token

    def _call_api(self, method, params):
        for attempt in range(2):
            result = self._request(method,{'token':self.get_access_token(),**params})
            if str(result.get('code')) == 'TK1002' and attempt == 0:
                self._access_token = None
                continue
            return self._check(result)

    def light_status(self, device_id, channel_id):
        data = self._call_api('getDeviceCameraStatus',{'deviceId':device_id,'channelId':channel_id,'enableType':'whiteLight'})
        state = str(data.get('status','')).lower()
        if state not in ('on','off'):
            raise CameraError('Cloud did not return a known spotlight state.')
        return state == 'on'

    def set_white_light(self, device_id, channel_id, enabled):
        self._call_api('setDeviceCameraStatus',{'deviceId':device_id,'channelId':channel_id,'enableType':'whiteLight','enable':bool(enabled)})
        return self.light_status(device_id,channel_id)



class CameraClient(CameraClient):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._session = requests.Session()
        self._digest = HTTPDigestAuth(self.username, self.password)
        self._onvif = None
        self._profiles = None
        self._ptz = None
        self._onvif_lock = threading.RLock()
        self._local_retry_at = 0.0
        self._local_failure = ''
        self._light_route = None

    def _create_onvif_camera(self):
        if self._onvif is not None:
            return self._onvif
        folders = (Path(onvif.__file__).parent/'wsdl',Path(onvif.__file__).parent.parent/'wsdl')
        wsdl = next((p for p in folders if (p/'devicemgmt.wsdl').is_file()),None)
        if wsdl is None:
            raise CameraError('ONVIF WSDL files are missing. Install requirements-app5.txt in a clean environment.')
        self._onvif = ONVIFCamera(self.host,self.port,self.username,self.password,str(wsdl),no_cache=True,transport=Transport(timeout=5,operation_timeout=5))
        return self._onvif

    def _ptz_context(self):
        camera = self._create_onvif_camera()
        if self._profiles is None:
            self._profiles = camera.create_media_service().GetProfiles()
        profile = next((p for p in self._profiles if getattr(p,'PTZConfiguration',None) is not None),None)
        if profile is None:
            raise CameraError('No PTZ-capable ONVIF profile found.')
        if self._ptz is None:
            self._ptz = camera.create_ptz_service()
        return self._ptz,profile.token

    def _invalidate_onvif(self):
        self._onvif = self._profiles = self._ptz = None

    def get_presets(self):
        with self._onvif_lock:
            try:
                ptz,token = self._ptz_context()
                return [{'token':str(p.token),'name':str(getattr(p,'Name','') or p.token)}
                        for p in ptz.GetPresets({'ProfileToken':token}) or [] if getattr(p,'token',None)]
            except Exception:
                self._invalidate_onvif()
                raise

    def goto_preset(self, token):
        with self._onvif_lock:
            try:
                ptz,profile = self._ptz_context()
                ptz.GotoPreset({'ProfileToken':profile,'PresetToken':token})
            except Exception:
                # Rebuild on the next command; do not replay a movement automatically.
                self._invalidate_onvif()
                raise

    def test_connection(self):
        camera = self._create_onvif_camera()
        try:
            profiles = camera.create_media_service().GetProfiles()
            if not profiles:
                raise CameraError('ONVIF login succeeded but the camera returned no media profiles.')
            self._profiles = profiles
            return True
        except CameraError:
            raise
        except Exception as exc:
            raise CameraError(f'ONVIF test failed ({type(exc).__name__}). Check camera username/password, ONVIF port and ONVIF support.') from None

    def _cgi(self, path):
        host = f'[{self.host}]' if ':' in self.host and not self.host.startswith('[') else self.host
        try:
            response = self._session.get(f'http://{host}:{self.port}{path}',auth=self._digest,timeout=(2,3),allow_redirects=False)
        except requests.RequestException as exc:
            raise CameraError(safe_error(exc)) from None
        if response.status_code in (401,403):
            raise CameraError(f'Local camera HTTP {response.status_code}: camera credentials or CGI permission rejected.')
        if response.status_code != 200:
            raise CameraError(f'Local camera HTTP {response.status_code}: the CGI control endpoint is unavailable on this port/firmware.')
        text = response.text.strip()
        if not text or text.startswith('<') or text.lower() == 'false' or re.search(r'\b(error|failed|failure)\b',text,re.I):
            raise CameraError('Camera rejected the CGI command or returned a login/error page.')
        return text

    @staticmethod
    def _parse_status(text):
        result = {}
        for line in text.splitlines():
            key,sep,value = line.partition('=')
            if not sep:
                continue
            key,value = key.strip().lower().split('.')[-1],value.strip().lower()
            if key != 'whitelight' or value not in ('on','off','1','0','true','false'):
                continue
            result['warning_light'] = value in ('on','1','true')
        return result

    def _local_status(self):
        if time.monotonic() < self._local_retry_at:
            raise CameraError(self._local_failure)
        # Keep the channel that actually returns deterrence status, including firmware using channel 0.
        candidates = [getattr(self,'_io_channel',1)]
        candidates += [c for c in (1,0) if c not in candidates]
        errors = []
        for channel in candidates:
            try:
                data = self._parse_status(self._cgi(f'/cgi-bin/coaxialControlIO.cgi?action=getStatus&channel={channel}'))
                if data:
                    self._io_channel = channel
                    self._light_route = 'local'
                    return data
                errors.append('No spotlight status returned')
            except CameraError as exc:
                errors.append(str(exc))
                if any(reason in str(exc).lower() for reason in ('401','403','timed out','cannot reach')):
                    break
        self._local_failure = 'Local spotlight status unavailable: '+errors[-1]
        self._local_retry_at = time.monotonic()+120
        raise CameraError(self._local_failure)

    def get_deterrence_status(self):
        if self._light_route == 'cloud' and self.cloud_client and self.cloud_device_id:
            try:
                return {'warning_light':self.cloud_client.light_status(self.cloud_device_id,self.cloud_channel_id)}
            except Exception:
                self._light_route = None
                raise
        local_error = None
        try:
            result = self._local_status()
        except CameraError as exc:
            local_error = exc
            result = {}
        if 'warning_light' not in result and self.cloud_client and self.cloud_device_id:
            try:
                result['warning_light'] = self.cloud_client.light_status(self.cloud_device_id,self.cloud_channel_id)
                self._light_route = 'cloud'
            except Exception as exc:
                if not result:
                    raise CameraError(f'{local_error or "Local light unavailable"} Cloud spotlight: {safe_error(exc)}') from None
        if not result:
            raise local_error or CameraError('No supported spotlight status endpoint found.')
        return result

    def _set_local(self, enabled):
        key = 'warning_light'
        status = self._local_status()
        if key not in status:
            raise CameraError(f'This firmware does not report local {key} support.')
        channel = self._io_channel
        # Direct camera control; TriggerMode=2 is an NVR variant, not needed here.
        # Use explicit force-off (2); support firmware requiring 0 only if read-back still says on.
        values = [1] if enabled else [2,0]
        for value in values:
            reply = self._cgi(f'/cgi-bin/coaxialControlIO.cgi?action=control&channel={channel}&info[0].Type=1&info[0].IO={value}')
            immediate = self._parse_status(reply)
            if immediate.get(key) is enabled:
                return enabled
            for attempt in range(3):
                time.sleep(.2)
                actual = self._local_status().get(key)
                if actual is enabled:
                    return actual
        raise CameraError(f'Camera did not confirm {key} {"on" if enabled else "off"}; no success state was published.')

    def set_warning_light(self, enabled):
        if self._light_route == 'cloud' and self.cloud_client and self.cloud_device_id:
            actual = self.cloud_client.set_white_light(self.cloud_device_id,self.cloud_channel_id,bool(enabled))
            if actual is not bool(enabled):
                raise CameraError('Cloud did not confirm the requested spotlight state.')
            return actual
        try:
            return self._set_local(bool(enabled))
        except CameraError as local_error:
            if self.cloud_client and self.cloud_device_id:
                try:
                    actual = self.cloud_client.set_white_light(self.cloud_device_id,self.cloud_channel_id,bool(enabled))
                    if actual is not bool(enabled):
                        raise CameraError('Cloud did not confirm the requested spotlight state.')
                    self._light_route = 'cloud'
                    return actual
                except Exception as exc:
                    raise CameraError(f'Local spotlight: {local_error} Cloud spotlight: {safe_error(exc)}') from None
            raise



def test_mqtt(config, wait_seconds=8):
    client = mqtt.Client(client_id=f'imou_test_{uuid.uuid4().hex[:12]}',callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    client.connect_timeout = wait_seconds
    event = threading.Event()
    outcome = []
    if config.username:
        client.username_pw_set(config.username,config.password)
    def connected(c,u,f,reason,p):
        outcome.append(None if not reason.is_failure else f'MQTT broker rejected login: {reason}')
        event.set()
    client.on_connect = connected
    try:
        client.connect(config.host,config.port,keepalive=15)
        client.loop_start()
        if not event.wait(wait_seconds):
            raise CameraError('MQTT connection timed out before the broker acknowledged login.')
        if outcome[0]:
            raise CameraError(outcome[0])
        return 'MQTT broker accepted the connection and credentials.'
    finally:
        try:
            client.disconnect()
        finally:
            client.loop_stop()


class Bridge(Bridge):
    def __init__(self,config,log_fn):
        super().__init__(copy.deepcopy(config),log_fn)
        self._command_lock = threading.Lock()

    def _setup_camera(self, cam_cfg):
        client = CameraClient(cam_cfg.host,cam_cfg.port,cam_cfg.username,cam_cfg.password,cloud_client=self.cloud_client,cloud_device_id=cam_cfg.cloud_device_id,cloud_channel_id=cam_cfg.cloud_channel_id)
        self._camera_clients[cam_cfg.device_id] = client
        presets,deterrence = [],{}
        onvif_ok = False
        try:
            client.test_connection()
            onvif_ok = True
            presets = client.get_presets()
        except Exception as exc:
            self.log(f'[{cam_cfg.name}] ONVIF/presets: {safe_error(exc)}')
        # Test spotlight separately: failure to fetch presets must not hide working controls.
        try:
            deterrence = client.get_deterrence_status()
        except Exception as exc:
            self.log(f'[{cam_cfg.name}] Spotlight: {safe_error(exc)}')
        self._presets[cam_cfg.device_id] = presets
        self._deterrence[cam_cfg.device_id] = deterrence
        if not self._running:
            return
        self._publish_discovery(cam_cfg,presets,deterrence)
        self._publish_availability(cam_cfg,'online' if onvif_ok or deterrence else 'offline')
        if 'warning_light' in deterrence:
            self._publish_light_state(cam_cfg,deterrence['warning_light'])
        self.log(f'[{cam_cfg.name}] {len(presets)} presets; spotlight {"available" if "warning_light" in deterrence else "unavailable"}.')

    def _on_connect(self,client,userdata,flags,reason_code,properties=None):
        if reason_code.is_failure:
            self.log(f'[mqtt] Connection rejected: {reason_code}')
            self._running = False
            return
        client.publish(f'{STATE_TOPIC_PREFIX}/bridge/status','online',retain=True)
        self.log('[mqtt] Broker accepted connection.')
        for cam in self.config.cameras:
            for action in ('start','stop'):
                old_topic = f'{self.config.mqtt.discovery_prefix}/button/{cam.device_id}_siren_{action}/config'
                client.publish(old_topic, '', qos=1, retain=True)
            client.unsubscribe(f'{STATE_TOPIC_PREFIX}/{cam.device_id}/siren/+/set')
        for cam in self.config.cameras:
            if cam.device_id in self._presets:
                self._publish_discovery(cam,self._presets[cam.device_id],self._deterrence.get(cam.device_id,{}))

    def _on_disconnect(self,client,userdata,disconnect_flags,reason_code,properties=None):
        self.log(f'[mqtt] Disconnected: {reason_code}')

    def _on_message(self,client,userdata,msg):
        if msg.retain or not self._running:
            return
        parts = msg.topic.split('/')
        value = msg.payload.decode('utf-8',errors='replace').strip().upper()
        if len(parts)<4 or parts[0]!=STATE_TOPIC_PREFIX or parts[-1]!='set':
            return
        kind=parts[2]
        valid = (kind=='light' and len(parts)==4 and value in ('ON','OFF')) or (kind=='preset' and len(parts)==5 and value=='PRESS')
        cam = next((c for c in self.config.cameras if c.device_id==parts[1]),None)
        camera = self._camera_clients.get(parts[1])
        if valid and cam and camera:
            threading.Thread(target=self._handle_command,args=(cam,camera,kind,parts,value),daemon=True).start()

    def _handle_command(self,cam_cfg,cam_client,kind,parts,payload):
        with self._command_lock:
            if not self._running:
                return
            try:
                if kind=='preset':
                    if parts[3] not in {p['token'] for p in self._presets.get(cam_cfg.device_id,[])}:
                        raise CameraError('Unknown preset token.')
                    cam_client.goto_preset(parts[3])
                elif kind=='light':
                    state=cam_client.set_warning_light(payload=='ON')
                    self._publish_light_state(cam_cfg,state)
                self.log(f'[{cam_cfg.name}] {kind} command confirmed.')
            except Exception as exc:
                self.log(f'[{cam_cfg.name}] {kind} failed: {safe_error(exc)}')

    def stop(self):
        self._running=False
        if self.client:
            try:
                self.client.publish(f'{STATE_TOPIC_PREFIX}/bridge/status','offline',retain=True)
                self._publish_all_availability('offline')
                self.client.disconnect()
            except Exception:
                pass


class App(App):
    def __init__(self):
        self._results=queue.Queue()
        self._busy=set()
        self._closing=False
        super().__init__()
        self.after(100,self._drain_results)
        if self.config_data.cameras:
            self.after(600,self._auto_connect)

    def _auto_connect(self):
        if self._closing or not self.config_data.cameras:
            return
        try:
            self._mqtt_config()
            self._cloud_config()
        except CameraError as exc:
            self._log(f'Automatic MQTT connection needs valid settings: {exc}')
            return
        self._start()

    def _add_camera(self):
        before = len(self.config_data.cameras)
        super()._add_camera()
        if len(self.config_data.cameras) > before:
            # The bridge holds a configuration snapshot; rebuild it to include the new camera.
            if self.bridge is not None:
                self._stop()
            self._auto_connect()

    def _refresh_camera_list(self):
        selected=self.tree.selection()
        # Original implementation is inlined here to preserve selection during test updates.
        self.tree.delete(*self.tree.get_children())
        for cam in self.config_data.cameras:
            icon,tag=self._status_display(cam.device_id)
            password=cam.password if self.show_passwords_var.get() else '•'*max(4,len(cam.password))
            self.tree.insert('', 'end',iid=cam.device_id,tags=(tag,),values=(icon,cam.name,cam.host,cam.port,cam.username,password))
        if selected and self.tree.exists(selected[0]):
            self.tree.selection_set(selected[0])
        self._autosize_columns()

    def _job(self,key,label,worker,done=None,popup=True):
        if key in self._busy:
            self._log(f'{label} is already running.')
            return
        self._busy.add(key)
        self._log(f'{label}: testing…')
        def run():
            try:
                result,error=worker(),None
            except Exception as exc:
                result,error=None,safe_error(exc)
            self._results.put((key,label,result,error,done,popup))
        threading.Thread(target=run,daemon=True).start()

    def _drain_results(self):
        if self._closing:
            return
        try:
            while True:
                key,label,result,error,done,popup=self._results.get_nowait()
                self._busy.discard(key)
                if done:
                    done(result,error)
                text=error or result or 'Connection successful.'
                self._log(f'{label}: {text}')
                if popup:
                    (messagebox.showerror if error else messagebox.showinfo)(label,text,parent=self)
        except queue.Empty:
            pass
        self.after(100,self._drain_results)

    def _mqtt_config(self):
        host=self.mqtt_vars['host'].get().strip()
        try:
            port=int(self.mqtt_vars['port'].get())
            if not 1<=port<=65535:
                raise ValueError()
        except ValueError:
            raise CameraError('MQTT port must be a number from 1 to 65535.')
        if not host or '://' in host or '/' in host:
            raise CameraError('Enter the MQTT broker hostname or IP address without a URL.')
        return MqttConfig(host,port,self.mqtt_vars['username'].get().strip(),self.mqtt_password_var.get(),self.mqtt_vars['discovery_prefix'].get().strip() or 'homeassistant')

    def _cloud_config(self):
        cfg=ImouCloudConfig(self.cloud_vars['app_id'].get().strip(),self.cloud_vars['app_secret'].get().strip(),self.cloud_vars['region'].get())
        if cfg.region not in CLOUD_URLS:
            raise CameraError('Choose a valid cloud data-center region.')
        return cfg

    def _test_mqtt_connection(self):
        try:
            cfg=self._mqtt_config()
        except CameraError as exc:
            messagebox.showerror('MQTT settings',str(exc),parent=self)
            return
        self._job('mqtt','MQTT connection',lambda:test_mqtt(cfg))

    def _test_cloud_connection(self):
        try:
            cfg=self._cloud_config()
            if not cfg.app_id or not cfg.app_secret:
                raise CameraError('App ID and App Secret are required.')
        except CameraError as exc:
            messagebox.showerror('Cloud settings',str(exc),parent=self)
            return
        def work():
            client=ImouCloudClient(cfg.app_id,cfg.app_secret,cfg.region)
            client.get_access_token()
            return 'Cloud application authentication succeeded. This tests App ID/App Secret only; it does not establish device-control permission (OP1009).'
        self._job('cloud','Cloud connection',work)

    def _test_camera_async(self,cam,popup=False):
        if ('camera',cam.device_id) in self._busy:
            return
        config=copy.deepcopy(cam)
        self.camera_status[cam.device_id]=None
        self._refresh_camera_list()
        def work():
            client=CameraClient(config.host,config.port,config.username,config.password)
            client.test_connection()
            return 'Camera ONVIF authentication succeeded and media profiles were returned.'
        def done(result,error):
            if any(c.device_id==config.device_id for c in self.config_data.cameras):
                self.camera_status[config.device_id]=error is None
                self._refresh_camera_list()
        self._job(('camera',cam.device_id),f'Camera connection — {cam.name}',work,done,popup)

    def _retest_selected(self):
        cam=self._selected_camera()
        if cam is None:
            messagebox.showinfo(APP_NAME,'Select a camera first.',parent=self)
            return
        self._test_camera_async(cam,popup=True)

    def _collect_configs(self):
        self.config_data.mqtt=self._mqtt_config()
        self.config_data.imou_cloud=self._cloud_config()

    def _start(self):
        if self.bridge and self.bridge._running:
            return
        if not self.config_data.cameras:
            messagebox.showinfo(APP_NAME,'Add at least one camera first.',parent=self)
            return
        try:
            self._collect_configs()
            self.config_data.save()
        except Exception as exc:
            messagebox.showerror(APP_NAME,safe_error(exc),parent=self)
            return
        self.bridge=Bridge(self.config_data,self._log)
        self.bridge.start()
        self.start_button.configure(state='disabled')
        self.stop_button.configure(state='normal')
        self._update_status()

    def _update_status(self):
        if self._closing or self.bridge is None:
            return
        if not self.bridge._running:
            self._stop()
            self.status_label.configure(text='Connection failed — see log',foreground='#c62828')
            return
        connected=self.bridge.client and self.bridge.client.is_connected()
        self.status_label.configure(text='MQTT connected' if connected else 'MQTT connecting / reconnecting',foreground='#2e7d32' if connected else '#986400')
        self.after(1000,self._update_status)

    def _on_close(self):
        self._closing=True
        if self.bridge:
            self.bridge.stop()
        for timer in self.tk.splitlist(self.tk.call('after','info')):
            self.after_cancel(timer)
        self.destroy()


class CameraDialog(CameraDialog):
    def _on_save(self):
        try:
            port=int(self.port_var.get())
            if not 1<=port<=65535:
                raise ValueError()
        except ValueError:
            messagebox.showerror('Invalid input','Camera port must be 1–65535.',parent=self)
            return
        name,host=self.name_var.get().strip(),self.host_var.get().strip()
        if not name or not host or any(c in host for c in '/@?#') or any(c.isspace() for c in host):
            messagebox.showerror('Invalid input','Enter a name and hostname/IP without a URL or path.',parent=self)
            return
        self.result=CameraConfig(name,host,port,self.username_var.get().strip(),self.password_var.get(),self.cloud_device_id_var.get().strip(),self.cloud_channel_id_var.get().strip() or '0')
        self.destroy()


if __name__ == '__main__':
    import sys
    if len(sys.argv) == 3 and sys.argv[1] == '--self-test':
        # Offline packaging check: no saved credentials, MQTT connections or camera commands.
        report = {'ok': False}
        try:
            from zeep import Client as SoapClient
            wsdl = next(p for p in (Path(onvif.__file__).parent/'wsdl',Path(onvif.__file__).parent.parent/'wsdl') if (p/'devicemgmt.wsdl').is_file())
            SoapClient(str(wsdl/'devicemgmt.wsdl'))
            AppConfig.load = classmethod(lambda cls: cls())
            app = App()
            app.withdraw()
            app.update_idletasks()
            app._on_close()
            report = {'ok':True,'checks':['Tk GUI initialization','ONVIF WSDL parsing','requests / MQTT / zeep imports'],'frozen':bool(getattr(sys,'frozen',False))}
        except Exception as exc:
            report['error'] = type(exc).__name__ + ': ' + str(exc)
        Path(sys.argv[2]).write_text(json.dumps(report,indent=2),encoding='utf-8')
        sys.exit(0 if report['ok'] else 1)
    else:
        App().mainloop()
