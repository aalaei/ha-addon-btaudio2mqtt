import os
import subprocess
import time
import json
import paho.mqtt.client as mqtt
import requests

# --- Global Configuration ---
HA_URL = os.getenv("SUPERVISOR_URL", "http://supervisor")
HA_TOKEN = os.getenv("SUPERVISOR_TOKEN")

MQTT_HOST = os.getenv("MQTT_HOST", "core-mosquitto")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER = os.getenv("MQTT_USER", "username_if_any")
MQTT_PASS = os.getenv("MQTT_PASSWORD", "password_if_any")

# Base topic for all devices this add-on creates
MQTT_BASE_TOPIC = "btaudio2mqtt"

print(f"Target: {MQTT_HOST}:{MQTT_PORT}", flush=True)
print(f"Credentials: {MQTT_USER}:{MQTT_PASS}", flush=True)

# --- Helper Functions ---

def run(cmd):
    """Executes a shell command and returns its output."""
    try:
        return subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.STDOUT).strip()
    except subprocess.CalledProcessError as e:
        print(f"Command failed: {cmd}\nOutput: {e.output}", flush=True)
        return ""

def generic_bluetoothctl(cmd: str):
    """
    Executes a bluetoothctl command directly using a pipe.
    This is more robust and has no dependency on HA shell_commands.
    """
    print(f"Executing bluetoothctl command: {cmd}", flush=True)
    try:
        # bluetoothctl is interactive, so we pipe commands to it.
        # A timeout is crucial in case it hangs (e.g., device not found).
        p = subprocess.run(
            f'echo -e "{cmd}\nquit" | bluetoothctl',
            shell=True,
            capture_output=True,
            text=True,
            timeout=10  # 10-second timeout
        )
        if p.stdout:
            print(f"bluetoothctl stdout: {p.stdout}", flush=True)
        if p.stderr:
            print(f"bluetoothctl stderr: {p.stderr}", flush=True)
        return p.stdout
    except subprocess.TimeoutExpired:
        print(f"ERROR: bluetoothctl command '{cmd}' timed out.", flush=True)
        return ""
    except Exception as e:
        print(f"ERROR: bluetoothctl command failed: {e}", flush=True)
        return ""

def reload_ha_audio():
    """Calls the Home Assistant API to reload the audio service."""
    print("Reloading Home Assistant Audio...", flush=True)
    headers = {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}
    url = f"{HA_URL}/audio/reload"
    try:
        resp = requests.post(url, headers=headers, timeout=5)
        if resp.ok:
            print(f"Audio reloaded successfully: {resp.text}", flush=True)
        else:
            print(f"Failed to reload Audio: {resp.status_code} {resp.text}", flush=True)
    except Exception as e:
        print(f"Error calling reload_ha_audio: {e}", flush=True)

def restart_vlc():
    """Calls the Home Assistant API to restart the VLC add-on."""
    print("Restarting VLC add-on...", flush=True)
    headers = {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}
    url = f"{HA_URL}/addons/core_vlc/restart"
    try:
        resp = requests.post(url, headers=headers, timeout=5)
        if resp.ok:
            print(f"VLC addon restarted successfully: {resp.text}", flush=True)
        else:
            print(f"Failed to restart VLC addon: {resp.status_code} {resp.text}", flush=True)
    except Exception as e:
        print(f"Error calling restart_vlc: {e}", flush=True)


# --- Main Speaker Class ---

class BluetoothSpeaker:
    """Manages a single Bluetooth speaker device."""
    
    def __init__(self, mac_address, friendly_name):
        self.mac = mac_address.upper()
        self.name = friendly_name.lower().replace(" ", "_") # Sanitized name
        self.friendly_name = friendly_name # Pretty name for HA
        
        # Define device-specific properties
        self.mac_sanitized = self.mac.replace(':', '_')
        self.sink_name = f"bluez_sink.{self.mac_sanitized}.a2dp_sink"
        self.topic_base = f"{MQTT_BASE_TOPIC}/{self.name}"
        self.unique_id_base = f"btaudio2mqtt_{self.name}"

        print(f"Initializing speaker: {self.friendly_name} ({self.mac}) on topic {self.topic_base}", flush=True)

    def get_status(self):
        """Gets the connection, volume, and mute status for this specific speaker."""
        # Find the specific sink for this device
        sink = run(f"pactl list short sinks | grep {self.sink_name} | awk '{{print $2}}'")
        
        if not sink:
            return {"connected": False, "volume": 0, "muted": False, "sink_name": self.sink_name}
        
        vol_str = run(f"pactl get-sink-volume {self.sink_name}")
        mute_str = run(f"pactl get-sink-mute {self.sink_name}")
        
        volume = int(vol_str.split('/')[1].replace('%', '').strip()) if '/' in vol_str else 0
        muted = "yes" in mute_str.lower()
        def_sink = run(f"pactl get-default-sink")
        
        return {
            "connected": True, 
            "volume": volume, 
            "muted": muted, 
            "sink_name": self.sink_name,
            "is_default_sink": self.sink_name == def_sink
        }

    def set_volume(self, level):
        """Sets the volume for this specific speaker."""
        print(f"[{self.name}] Setting volume to {level}%", flush=True)
        run(f"pactl set-sink-volume {self.sink_name} {level}%")

    def set_mute(self, state):
        """Sets the mute state for this specific speaker."""
        mute_val = '1' if state else '0'
        print(f"[{self.name}] Setting mute to {mute_val}", flush=True)
        run(f"pactl set-sink-mute {self.sink_name} {mute_val}")

    def set_as_default_sink(self):
        """Sets this speaker as the default PulseAudio sink."""
        print(f"[{self.name}] Setting as default sink", flush=True)
        run(f"pactl set-default-sink {self.sink_name}")
        # Reloading audio and VLC is a good idea after this
        reload_ha_audio()
        restart_vlc()

    def connect(self):
        print(f"[{self.name}] Connecting...", flush=True)
        generic_bluetoothctl(f'connect {self.mac}')

    def disconnect(self):
        print(f"[{self.name}] Disconnecting...", flush=True)
        generic_bluetoothctl(f'disconnect {self.mac}')

    def pair(self):
        print(f"[{self.name}] Pairing and trusting...", flush=True)
        generic_bluetoothctl(f'pair {self.mac}')
        generic_bluetoothctl(f'trust {self.mac}')

    def unpair(self):
        print(f"[{self.name}] Unpairing (removing)...", flush=True)
        generic_bluetoothctl(f'remove {self.mac}')

    def publish_discovery(self, client):
        """Publishes all MQTT discovery payloads for this device."""
        print(f"[{self.name}] Publishing MQTT discovery messages...", flush=True)

        # Device payload (groups all entities)
        device_payload = {
            "identifiers": [self.unique_id_base],
            "name": self.friendly_name,
            "manufacturer": "Bluetooth Audio MQTT Bridge",
            "model": f"PulseAudio Control ({self.mac})"
        }

        # --- Define all entity configs ---
        
        # 1. Volume Number
        vol_config = {
            "name": "Volume",
            "unique_id": f"{self.unique_id_base}_volume",
            "command_topic": f"{self.topic_base}/set/volume",
            "state_topic": f"{self.topic_base}/state/volume",
            "min": 0, "max": 100, "step": 1,
            "icon": "mdi:volume-high",
            "device": device_payload
        }
        
        # 2. Mute Switch
        mute_config = {
            "name": "Mute",
            "unique_id": f"{self.unique_id_base}_mute",
            "command_topic": f"{self.topic_base}/set/mute",
            "state_topic": f"{self.topic_base}/state/mute",
            "payload_on": "ON", "payload_off": "OFF",
            "icon": "mdi:volume-mute",
            "device": device_payload
        }

        # 3. Connect Switch
        connect_config = {
            "name": "Connect",
            "unique_id": f"{self.unique_id_base}_connect",
            "command_topic": f"{self.topic_base}/set/connect",
            "state_topic": f"{self.topic_base}/state/connection",
            "payload_on": "ON", "payload_off": "OFF",
            "icon": "mdi:bluetooth-connect",
            "device": device_payload
        }

        # 4. Set Sink Button
        sink_config = {
            "name": "Set as Default Sink",
            "unique_id": f"{self.unique_id_base}_setsink",
            "command_topic": f"{self.topic_base}/set/setsink",
            "payload_press": "PRESS",
            "icon": "mdi:audio-video",
            "device": device_payload
        }

        # 5. Status Binary Sensor
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
        
        # 6. Pair Button
        pair_config = {
            "name": "Pair Device",
            "unique_id": f"{self.unique_id_base}_pair_bt",
            "command_topic": f"{self.topic_base}/set/pair",
            "payload_press": "PRESS",
            "icon": "mdi:bluetooth-settings",
            "entity_category": "config",
            "device": device_payload
        }

        # 7. Unpair Button
        unpair_config = {
            "name": "Unpair Device",
            "unique_id": f"{self.unique_id_base}_unpair_bt",
            "command_topic": f"{self.topic_base}/set/unpair",
            "payload_press": "PRESS",
            "icon": "mdi:bluetooth-off",
            "entity_category": "config",
            "device": device_payload
        }

        # --- Publish all configs ---
        client.publish(f"homeassistant/number/{self.unique_id_base}_volume/config", json.dumps(vol_config), qos=1, retain=True)
        client.publish(f"homeassistant/switch/{self.unique_id_base}_mute/config", json.dumps(mute_config), qos=1, retain=True)
        client.publish(f"homeassistant/switch/{self.unique_id_base}_connect/config", json.dumps(connect_config), qos=1, retain=True)
        client.publish(f"homeassistant/button/{self.unique_id_base}_setsink/config", json.dumps(sink_config), qos=1, retain=True)
        client.publish(f"homeassistant/binary_sensor/{self.unique_id_base}_status/config", json.dumps(status_config), qos=1, retain=True)
        client.publish(f"homeassistant/button/{self.unique_id_base}_pair_bt/config", json.dumps(pair_config), qos=1, retain=True)
        client.publish(f"homeassistant/button/{self.unique_id_base}_unpair_bt/config", json.dumps(unpair_config), qos=1, retain=True)
        
        print(f"[{self.name}] Discovery messages published.", flush=True)

    def publish_state(self, client):
        """Gets and publishes the current state for this speaker."""
        try:
            status = self.get_status()
            connection_state = "ON" if status["connected"] else "OFF"
            mute_state = "ON" if status["muted"] else "OFF"
            
            # Publish full JSON status
            client.publish(f"{self.topic_base}/status", json.dumps(status), retain=True)
            # Publish individual states for HA entities
            client.publish(f"{self.topic_base}/state/connection", connection_state, retain=True)
            client.publish(f"{self.topic_base}/state/volume", str(status["volume"]), retain=True)
            client.publish(f"{self.topic_base}/state/mute", mute_state, retain=True)
        except Exception as e:
            print(f"Error in publish_state for {self.name}: {e}", flush=True)


# --- Main Application Logic ---

def load_configured_devices():
    """Loads device configuration from /data/options.json."""
    devices = []
    config_path = '/data/options.json'
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        
        device_configs = config.get('devices', [])
        if not device_configs:
            print("WARNING: No devices configured. Add devices in the add-on 'Configuration' tab.", flush=True)
            return []

        for dev_config in device_configs:
            if 'mac_address' in dev_config and 'friendly_name' in dev_config:
                devices.append(BluetoothSpeaker(
                    mac_address=dev_config['mac_address'],
                    friendly_name=dev_config['friendly_name']
                ))
            else:
                print(f"Skipping invalid device config: {dev_config}", flush=True)
        
        return devices
    except FileNotFoundError:
        print(f"ERROR: Configuration file not found at {config_path}. Did you set options?", flush=True)
        return []
    except json.JSONDecodeError:
        print(f"ERROR: Could not decode JSON from {config_path}. File is corrupt.", flush=True)
        return []
    except Exception as e:
        print(f"Error loading configuration: {e}", flush=True)
        return []

# --- MQTT Callbacks ---

# We store the list of speaker objects globally
speakers = []

def on_connect(client, userdata, flags, rc, properties=None):
    """Called when MQTT connects."""
    if rc == 0:
        print("MQTT connected successfully.", flush=True)
        # Subscribe to the command topic for ALL configured devices
        # 'btaudio2mqtt/+/set/#' means it will match any speaker name
        client.subscribe(f"{MQTT_BASE_TOPIC}/+/set/#")
        
        # Publish discovery for all configured speakers
        for speaker in speakers:
            speaker.publish_discovery(client)
    else:
        print(f"MQTT connection failed with code {rc}", flush=True)

def on_message(client, userdata, msg, properties=None):
    """Called when an MQTT message is received."""
    topic = msg.topic
    payload = msg.payload.decode()
    print(f"MQTT RX: {topic} -> {payload}", flush=True)
    
    try:
        # Topic structure: btaudio2mqtt/[speaker_name]/set/[command]
        topic_parts = topic.split('/')
        if len(topic_parts) != 4 or topic_parts[0] != MQTT_BASE_TOPIC or topic_parts[2] != 'set':
            return # Not a valid command topic

        target_name = topic_parts[1]
        command = topic_parts[3]

        # Find the speaker object this command is for
        target_speaker = next((s for s in speakers if s.name == target_name), None)
        
        if not target_speaker:
            print(f"Received command for unknown speaker: {target_name}", flush=True)
            return

        # Route the command to the correct speaker's method
        if command == "volume":
            target_speaker.set_volume(int(payload))
        elif command == "mute":
            target_speaker.set_mute(payload.lower() == "on")
        elif command == "connect":
            if payload.lower() == "on":
                target_speaker.connect()
            else:
                target_speaker.disconnect()
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
if __name__ == "__main__":
    # 1. Load devices from config
    speakers = load_configured_devices()
    
    if not speakers:
        print("No speakers loaded. Exiting.", flush=True)
        time.sleep(60) # Sleep to avoid rapid container restarts
        exit(1)

    # 2. Setup and connect MQTT client
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

    # 3. Main loop to periodically update all device states
    while True:
        try:
            print("--- Main loop: Updating all speaker states ---", flush=True)
            for speaker in speakers:
                speaker.publish_state(client)
            print("--- Main loop: Update complete ---", flush=True)
        except Exception as e:
            print(f"Error in main loop: {e}", flush=True)
        
        # Update states every 10 seconds
        time.sleep(10)