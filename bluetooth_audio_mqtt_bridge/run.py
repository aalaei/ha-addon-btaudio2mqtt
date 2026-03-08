import os
import subprocess
import threading
import time
import json
import paho.mqtt.client as mqtt
import requests

# --- Environment (MQTT credentials injected by run.sh) ---
HA_URL = os.getenv("SUPERVISOR_URL", "http://supervisor")
HA_TOKEN = os.getenv("SUPERVISOR_TOKEN")

MQTT_HOST = os.getenv("MQTT_HOST", "core-mosquitto")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER = os.getenv("MQTT_USER", "")
MQTT_PASS = os.getenv("MQTT_PASSWORD", "")

# These globals are overridden by load_config() after reading /data/options.json
MQTT_BASE_TOPIC = "btaudio2mqtt"
POLL_INTERVAL = 10
AUTO_RECONNECT = True

print(f"Target: {MQTT_HOST}:{MQTT_PORT}", flush=True)


# --- Helper Functions ---

def run(cmd):
    """Executes a shell command and returns stdout only (stderr suppressed)."""
    try:
        result = subprocess.run(
            cmd, shell=True, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10
        )
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        print(f"Command timed out: {cmd}", flush=True)
        return ""
    except Exception as e:
        print(f"Command error ({cmd}): {e}", flush=True)
        return ""


def ha_get(path):
    """GET request to the HA Supervisor API."""
    headers = {"Authorization": f"Bearer {HA_TOKEN}"}
    try:
        resp = requests.get(f"{HA_URL}{path}", headers=headers, timeout=5)
        if resp.ok:
            return resp.json().get("data", {})
        print(f"HA API GET {path} failed: {resp.status_code}", flush=True)
    except Exception as e:
        print(f"HA API GET {path} error: {e}", flush=True)
    return {}


def ha_post(path, payload=None):
    """POST request to the HA Supervisor API."""
    headers = {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}
    try:
        resp = requests.post(f"{HA_URL}{path}", headers=headers, json=payload, timeout=5)
        return resp.ok
    except Exception as e:
        print(f"HA API POST {path} error: {e}", flush=True)
        return False


def get_audio_info():
    """Fetch current audio state from the HA Supervisor API."""
    data = ha_get("/audio/info")
    return data.get("audio", {})


def generic_bluetoothctl(cmd: str):
    """Executes a bluetoothctl command via pipe."""
    print(f"Executing bluetoothctl: {cmd}", flush=True)
    try:
        p = subprocess.run(
            f'echo -e "{cmd}\nquit" | bluetoothctl',
            shell=True, capture_output=True, text=True, timeout=15
        )
        if p.stdout:
            print(f"bluetoothctl stdout: {p.stdout}", flush=True)
        if p.stderr:
            print(f"bluetoothctl stderr: {p.stderr}", flush=True)
        return p.stdout
    except subprocess.TimeoutExpired:
        print(f"ERROR: bluetoothctl '{cmd}' timed out.", flush=True)
        return ""
    except Exception as e:
        print(f"ERROR: bluetoothctl failed: {e}", flush=True)
        return ""


def reload_ha_audio():
    """Calls the HA API to reload the audio service."""
    ok = ha_post("/audio/reload")
    print(f"Audio reload: {'OK' if ok else 'FAILED'}", flush=True)


def restart_vlc():
    """Calls the HA API to restart the VLC add-on (if present)."""
    headers = {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}
    try:
        resp = requests.post(f"{HA_URL}/addons/core_vlc/restart", headers=headers, timeout=5)
        print(f"VLC restart: {resp.status_code}", flush=True)
    except Exception as e:
        print(f"Error restarting VLC: {e}", flush=True)


# --- Main Speaker Class ---

class BluetoothSpeaker:
    """Manages a single Bluetooth speaker: state polling, MQTT discovery, and control."""

    def __init__(self, mac_address, friendly_name, auto_connect=False, reconnect_attempts=3):
        self.mac = mac_address.upper()
        self.name = friendly_name.lower().replace(" ", "_")
        self.friendly_name = friendly_name
        self.auto_connect = auto_connect
        self.reconnect_attempts = reconnect_attempts

        self.mac_sanitized = self.mac.replace(':', '_')
        # Expected names in PulseAudio / HA audio system
        self.card_name = f"bluez_card.{self.mac_sanitized}"
        self.sink_name = f"bluez_sink.{self.mac_sanitized}.a2dp_sink"

        self.topic_base = f"{MQTT_BASE_TOPIC}/{self.name}"
        self.unique_id_base = f"btaudio2mqtt_{self.name}"
        self._last_known_connected = False
        self._output_index = None       # cached sink index for API calls
        self._user_wants_connected = True  # False after explicit disconnect; prevents auto-reconnect
        self._connecting = False        # guard: only one connect attempt at a time
        self._last_audio_reload = 0     # throttle audio reloads (timestamp)

        print(f"Initializing speaker: {self.friendly_name} ({self.mac}) -> topic: {self.topic_base}", flush=True)

    def _find_output_in_audio(self, audio):
        """Find this device's output entry in HA audio info (by MAC)."""
        for output in audio.get("output", []):
            if self.mac_sanitized.lower() in output.get("name", "").lower():
                return output
        return None

    def is_bluetooth_connected(self, audio=None):
        """Checks true Bluetooth connection state.

        Priority:
        1. bluetoothctl info {MAC} — ground truth from the BT daemon itself.
           PulseAudio cards/sinks persist after disconnection, so the supervisor
           API alone cannot be trusted. bluetoothctl reads the actual HCI state.
        2. Supervisor API card + A2DP profile active — fallback if bluetoothctl
           gives no useful output (e.g. D-Bus issue).

        If BT reports connected but the PA card is missing, triggers an audio
        reload to re-register it (throttled to prevent reload storms).
        """
        # --- Primary: bluetoothctl ---
        bt_out = run(f"bluetoothctl info {self.mac}")

        if "Connected:" in bt_out:
            bt_connected = "Connected: yes" in bt_out

            # BT connected but no PulseAudio card yet → reload audio to register it
            if bt_connected:
                if audio is None:
                    audio = get_audio_info()
                has_card = any(c.get("name") == self.card_name for c in audio.get("card", []))
                if not has_card:
                    now = time.time()
                    if now - self._last_audio_reload >= 30:
                        print(f"[{self.name}] BT connected but no PA card — reloading audio", flush=True)
                        self._last_audio_reload = now
                        reload_ha_audio()

            print(f"[{self.name}] connected={bt_connected} (via bluetoothctl)", flush=True)
            return bt_connected

        # --- Fallback: supervisor API card with A2DP profile check ---
        # Only reached if bluetoothctl gave no output (e.g. D-Bus unavailable)
        if audio is None:
            audio = get_audio_info()
        for card in audio.get("card", []):
            if card.get("name") == self.card_name:
                profiles = card.get("profiles", [])
                a2dp_active = any(
                    p.get("name") in ("a2dp_sink", "a2dp") and p.get("active", False)
                    for p in profiles
                )
                if not a2dp_active and self._user_wants_connected:
                    now = time.time()
                    if now - self._last_audio_reload >= 60:
                        print(f"[{self.name}] Card present but A2DP inactive — reloading audio", flush=True)
                        self._last_audio_reload = now
                        reload_ha_audio()
                        time.sleep(2)
                        audio = get_audio_info()
                        for c in audio.get("card", []):
                            if c.get("name") == self.card_name:
                                a2dp_active = any(
                                    p.get("name") in ("a2dp_sink", "a2dp") and p.get("active", False)
                                    for p in c.get("profiles", [])
                                )
                print(f"[{self.name}] connected={a2dp_active} (via PA profile fallback)", flush=True)
                return a2dp_active

        print(f"[{self.name}] connected=False (no card found)", flush=True)
        return False

    def get_status(self):
        """Gets the connection, volume, and mute status for this speaker."""
        audio = get_audio_info()
        connected = self.is_bluetooth_connected(audio)

        if not connected:
            return {
                "connected": False,
                "volume": 0,
                "muted": False,
                "sink_name": self.sink_name
            }

        output = self._find_output_in_audio(audio)
        print(f"[{self.name}] output entry: {output}", flush=True)

        volume = 0
        muted = False
        actual_sink = self.sink_name

        if output:
            actual_sink = output.get("name", self.sink_name)
            self._output_index = output.get("index")  # cache for set_volume / set_mute
            # Supervisor API reports volume as float 0.0–1.0; convert to integer 0–100
            raw_vol = output.get("volume", 0)
            volume = int(round(float(raw_vol) * 100))
            muted = bool(output.get("mute", False))

        default_output = audio.get("default", {}).get("output", "")

        return {
            "connected": True,
            "volume": volume,
            "muted": muted,
            "sink_name": actual_sink,
            "is_default_sink": actual_sink == default_output
        }

    def _get_output_index(self):
        """Returns cached output index, fetching it from the API if needed."""
        if self._output_index is None:
            audio = get_audio_info()
            output = self._find_output_in_audio(audio)
            if output:
                self._output_index = output.get("index")
        return self._output_index

    def set_volume(self, level):
        """Sets volume via HA Supervisor audio API.

        API expects: {"index": sink_index, "volume": float 0.0–1.0}
        """
        print(f"[{self.name}] Setting volume to {level}%", flush=True)
        idx = self._get_output_index()
        if idx is None:
            print(f"[{self.name}] Cannot set volume: device not connected", flush=True)
            return
        ok = ha_post("/audio/volume/output", {"index": idx, "volume": round(level / 100.0, 4)})
        if not ok:
            print(f"[{self.name}] Volume set failed", flush=True)

    def set_mute(self, state):
        """Sets mute state via HA Supervisor audio API.

        API expects: {"index": sink_index, "active": bool}  (field is 'active', not 'muted')
        """
        print(f"[{self.name}] Setting mute to {state}", flush=True)
        idx = self._get_output_index()
        if idx is None:
            print(f"[{self.name}] Cannot set mute: device not connected", flush=True)
            return
        ha_post("/audio/mute/output", {"index": idx, "active": state})

    def set_as_default_sink(self):
        """Sets this device as the default output via supervisor API."""
        print(f"[{self.name}] Setting as default output", flush=True)
        ok = ha_post("/audio/default/output", {"output": self.sink_name})
        if ok:
            reload_ha_audio()
            restart_vlc()
        else:
            print(f"[{self.name}] Default sink set failed", flush=True)

    def _bt_connect(self):
        """Low-level bluetoothctl connect."""
        generic_bluetoothctl(f'connect {self.mac}')

    def _bt_disconnect(self):
        """Low-level bluetoothctl disconnect."""
        generic_bluetoothctl(f'disconnect {self.mac}')

    def pair(self):
        print(f"[{self.name}] Pairing and trusting...", flush=True)
        generic_bluetoothctl(f'pair {self.mac}')
        generic_bluetoothctl(f'trust {self.mac}')

    def unpair(self):
        print(f"[{self.name}] Unpairing (removing)...", flush=True)
        generic_bluetoothctl(f'remove {self.mac}')

    def try_connect(self, client):
        """Try to connect with retries. Publishes the true result back to MQTT immediately.

        Runs in a background thread so MQTT message processing is not blocked.
        If all attempts fail, publishes OFF so the HA switch reflects reality.
        """
        if self._connecting:
            print(f"[{self.name}] Already attempting to connect, ignoring.", flush=True)
            return
        self._connecting = True
        self._user_wants_connected = True
        print(f"[{self.name}] Attempting to connect ({self.reconnect_attempts} attempts max)...", flush=True)

        try:
            for attempt in range(1, self.reconnect_attempts + 1):
                print(f"[{self.name}] Connect attempt {attempt}/{self.reconnect_attempts}", flush=True)
                self._bt_connect()
                time.sleep(4)
                # Reload audio so PulseAudio registers the newly connected BT card
                self._last_audio_reload = time.time()
                reload_ha_audio()
                time.sleep(3)
                if self.is_bluetooth_connected():
                    print(f"[{self.name}] Connected successfully.", flush=True)
                    self._last_known_connected = True
                    client.publish(f"{self.topic_base}/state/connection", "ON", retain=True)
                    return

            # All attempts failed — tell HA the switch is OFF
            print(f"[{self.name}] All connect attempts failed. Reporting as disconnected.", flush=True)
            self._user_wants_connected = False
            self._last_known_connected = False
            client.publish(f"{self.topic_base}/state/connection", "OFF", retain=True)
        finally:
            self._connecting = False

    def do_disconnect(self, client):
        """Disconnect and disable auto-reconnect for this device.

        Runs in a background thread. Publishes OFF immediately so the HA switch
        updates without waiting for the next poll cycle.
        """
        print(f"[{self.name}] Disconnecting (user requested).", flush=True)
        self._user_wants_connected = False
        self._last_known_connected = False
        self._output_index = None
        self._bt_disconnect()
        client.publish(f"{self.topic_base}/state/connection", "OFF", retain=True)

    def maybe_reconnect(self, client):
        """Auto-reconnect if the device dropped unexpectedly (not user-requested)."""
        if not AUTO_RECONNECT or not self._user_wants_connected:
            print(
                f"[{self.name}] Not reconnecting "
                f"(auto_reconnect={AUTO_RECONNECT}, user_wants={self._user_wants_connected})",
                flush=True
            )
            return
        print(f"[{self.name}] Connection dropped unexpectedly. Auto-reconnecting...", flush=True)
        self.try_connect(client)

    def publish_discovery(self, client):
        """Publishes all MQTT discovery payloads for this device."""
        print(f"[{self.name}] Publishing MQTT discovery messages...", flush=True)

        device_payload = {
            "identifiers": [self.unique_id_base],
            "name": self.friendly_name,
            "manufacturer": "Bluetooth Audio MQTT Bridge",
            "model": f"PulseAudio Control ({self.mac})"
        }

        vol_config = {
            "name": "Volume",
            "unique_id": f"{self.unique_id_base}_volume",
            "command_topic": f"{self.topic_base}/set/volume",
            "state_topic": f"{self.topic_base}/state/volume",
            "min": 0, "max": 100, "step": 1,
            "icon": "mdi:volume-high",
            "device": device_payload
        }

        mute_config = {
            "name": "Mute",
            "unique_id": f"{self.unique_id_base}_mute",
            "command_topic": f"{self.topic_base}/set/mute",
            "state_topic": f"{self.topic_base}/state/mute",
            "payload_on": "ON", "payload_off": "OFF",
            "icon": "mdi:volume-mute",
            "device": device_payload
        }

        connect_config = {
            "name": "Connect",
            "unique_id": f"{self.unique_id_base}_connect",
            "command_topic": f"{self.topic_base}/set/connect",
            "state_topic": f"{self.topic_base}/state/connection",
            "payload_on": "ON", "payload_off": "OFF",
            "icon": "mdi:bluetooth-connect",
            "device": device_payload
        }

        sink_config = {
            "name": "Set as Default Sink",
            "unique_id": f"{self.unique_id_base}_setsink",
            "command_topic": f"{self.topic_base}/set/setsink",
            "payload_press": "PRESS",
            "icon": "mdi:audio-video",
            "device": device_payload
        }

        status_config = {
            "name": "Status",
            "unique_id": f"{self.unique_id_base}_status",
            "state_topic": f"{self.topic_base}/state/connection",
            "payload_on": "ON", "payload_off": "OFF",
            "device_class": "connectivity",
            "icon": "mdi:bluetooth",
            "json_attributes_topic": f"{self.topic_base}/status",
            "device": device_payload
        }

        pair_config = {
            "name": "Pair Device",
            "unique_id": f"{self.unique_id_base}_pair_bt",
            "command_topic": f"{self.topic_base}/set/pair",
            "payload_press": "PRESS",
            "icon": "mdi:bluetooth-settings",
            "entity_category": "config",
            "device": device_payload
        }

        unpair_config = {
            "name": "Unpair Device",
            "unique_id": f"{self.unique_id_base}_unpair_bt",
            "command_topic": f"{self.topic_base}/set/unpair",
            "payload_press": "PRESS",
            "icon": "mdi:bluetooth-off",
            "entity_category": "config",
            "device": device_payload
        }

        client.publish(f"homeassistant/number/{self.unique_id_base}_volume/config",        json.dumps(vol_config),     qos=1, retain=True)
        client.publish(f"homeassistant/switch/{self.unique_id_base}_mute/config",          json.dumps(mute_config),    qos=1, retain=True)
        client.publish(f"homeassistant/switch/{self.unique_id_base}_connect/config",       json.dumps(connect_config), qos=1, retain=True)
        client.publish(f"homeassistant/button/{self.unique_id_base}_setsink/config",       json.dumps(sink_config),    qos=1, retain=True)
        client.publish(f"homeassistant/binary_sensor/{self.unique_id_base}_status/config", json.dumps(status_config),  qos=1, retain=True)
        client.publish(f"homeassistant/button/{self.unique_id_base}_pair_bt/config",       json.dumps(pair_config),    qos=1, retain=True)
        client.publish(f"homeassistant/button/{self.unique_id_base}_unpair_bt/config",     json.dumps(unpair_config),  qos=1, retain=True)

        print(f"[{self.name}] Discovery messages published.", flush=True)

    def publish_state(self, client):
        """Gets and publishes the current state for this speaker."""
        try:
            status = self.get_status()
            currently_connected = status["connected"]

            # Detect a drop and trigger reconnect before publishing state
            if self._last_known_connected and not currently_connected:
                self.maybe_reconnect(client)
                status = self.get_status()
                currently_connected = status["connected"]

            self._last_known_connected = currently_connected

            connection_state = "ON" if currently_connected else "OFF"
            mute_state = "ON" if status["muted"] else "OFF"

            client.publish(f"{self.topic_base}/status",           json.dumps(status),    retain=True)
            client.publish(f"{self.topic_base}/state/connection", connection_state,       retain=True)
            client.publish(f"{self.topic_base}/state/volume",     str(status["volume"]), retain=True)
            client.publish(f"{self.topic_base}/state/mute",       mute_state,            retain=True)
        except Exception as e:
            print(f"Error in publish_state for {self.name}: {e}", flush=True)


# --- Configuration Loader ---

def load_config():
    """Loads full configuration from /data/options.json and returns speaker list."""
    global MQTT_BASE_TOPIC, POLL_INTERVAL, AUTO_RECONNECT

    config_path = '/data/options.json'
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
    except FileNotFoundError:
        print(f"ERROR: Config not found at {config_path}", flush=True)
        return []
    except json.JSONDecodeError:
        print(f"ERROR: Invalid JSON at {config_path}", flush=True)
        return []

    MQTT_BASE_TOPIC = config.get('mqtt_base_topic', 'btaudio2mqtt')
    POLL_INTERVAL = int(config.get('poll_interval', 10))
    AUTO_RECONNECT = bool(config.get('auto_reconnect', True))

    print(f"Config: topic={MQTT_BASE_TOPIC}, poll={POLL_INTERVAL}s, auto_reconnect={AUTO_RECONNECT}", flush=True)

    devices = []
    for dev_conf in config.get('devices', []):
        if 'mac_address' not in dev_conf or 'friendly_name' not in dev_conf:
            print(f"Skipping invalid device entry: {dev_conf}", flush=True)
            continue
        devices.append(BluetoothSpeaker(
            mac_address=dev_conf['mac_address'],
            friendly_name=dev_conf['friendly_name'],
            auto_connect=dev_conf.get('auto_connect', False),
            reconnect_attempts=dev_conf.get('reconnect_attempts', 3),
        ))

    if not devices:
        print("WARNING: No devices configured. Add devices in the add-on Configuration tab.", flush=True)

    return devices


# --- MQTT Callbacks ---

speakers = []


def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print("MQTT connected successfully.", flush=True)
        client.subscribe(f"{MQTT_BASE_TOPIC}/+/set/#")
        for speaker in speakers:
            speaker.publish_discovery(client)
    else:
        print(f"MQTT connection failed with code {rc}", flush=True)


def on_message(client, userdata, msg, properties=None):
    topic = msg.topic
    payload = msg.payload.decode()
    print(f"MQTT RX: {topic} -> {payload}", flush=True)

    try:
        parts = topic.split('/')
        if len(parts) != 4 or parts[0] != MQTT_BASE_TOPIC or parts[2] != 'set':
            return

        target_name = parts[1]
        command = parts[3]

        target_speaker = next((s for s in speakers if s.name == target_name), None)
        if not target_speaker:
            print(f"Command for unknown speaker: {target_name}", flush=True)
            return

        if command == "volume":
            target_speaker.set_volume(int(payload))
        elif command == "mute":
            target_speaker.set_mute(payload.lower() == "on")
        elif command == "connect":
            if payload.lower() == "on":
                threading.Thread(target=target_speaker.try_connect, args=(client,), daemon=True).start()
            else:
                threading.Thread(target=target_speaker.do_disconnect, args=(client,), daemon=True).start()
        elif command == "setsink":
            if payload == "PRESS":
                target_speaker.set_as_default_sink()
        elif command == "pair":
            if payload == "PRESS":
                target_speaker.pair()
        elif command == "unpair":
            if payload == "PRESS":
                target_speaker.unpair()

    except Exception as e:
        print(f"Error processing MQTT message: {e}", flush=True)


# --- Startup ---

def diagnostics():
    """Run startup diagnostics to surface environment issues early."""
    print("=== DIAGNOSTICS ===", flush=True)
    audio = get_audio_info()
    print(
        f"Supervisor audio info: "
        f"cards={[c.get('name') for c in audio.get('card', [])]} "
        f"outputs={[o.get('name') for o in audio.get('output', [])]}",
        flush=True
    )

    # Test bluetoothctl availability (critical for connection detection)
    result = subprocess.run(
        "bluetoothctl --version", shell=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5
    )
    print(f"bluetoothctl version: {result.stdout.strip() or result.stderr.strip()}", flush=True)

    print("=== END DIAGNOSTICS ===", flush=True)


if __name__ == "__main__":
    diagnostics()
    speakers = load_config()

    if not speakers:
        print("No speakers loaded. Exiting.", flush=True)
        time.sleep(60)
        exit(1)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect(MQTT_HOST, MQTT_PORT, 60)
        client.loop_start()
    except Exception as e:
        print(f"ERROR: MQTT connect() failed: {e}", flush=True)
        exit(1)

    # Auto-connect devices flagged for it (after MQTT is up so state can be published)
    time.sleep(2)
    for speaker in speakers:
        if speaker.auto_connect:
            threading.Thread(target=speaker.try_connect, args=(client,), daemon=True).start()

    while True:
        try:
            print("--- Updating speaker states ---", flush=True)
            for speaker in speakers:
                speaker.publish_state(client)
        except Exception as e:
            print(f"Error in main loop: {e}", flush=True)

        time.sleep(POLL_INTERVAL)
