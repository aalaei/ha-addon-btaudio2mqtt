# Bluetooth Audio MQTT Bridge - Home Assistant Add-on

[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg?style=for-the-badge)](https://github.com/hacs/integration)
![GitHub Release](https://img.shields.io/github/v/release/aalaei/ha-addon-btaudio2mqtt?style=for-the-badge)
![GitHub commits](https://img.shields.io/github/commit-activity/m/aalaei/ha-addon-btaudio2mqtt?style=for-the-badge)

Control multiple Bluetooth speakers and sinks directly from Home Assistant.

This add-on discovers Bluetooth speakers paired with your Home Assistant host, creates a new HA device for each one, and provides entities to control connection, volume, mute, and default sink selection via MQTT.

[![Open your Home Assistant instance and add this repository.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https://github.com/aalaei/ha-addon-btaudio2mqtt)

---

## Features

- **Multi-Device Support**: Configure any number of Bluetooth speakers, each with its own set of HA entities.
- **Auto-Discovery**: Each configured speaker gets its own device in Home Assistant via MQTT Discovery.
- **Accurate Connection State**: Uses `bluetoothctl` as ground truth for Bluetooth state. PulseAudio cards persist in memory after disconnection — this add-on reads directly from the Bluetooth daemon to avoid false "connected" readings.
- **Full Control**: Each speaker exposes the following entities:
  - **Connect / Disconnect** (Switch) — with retry logic and auto-reconnect on unexpected drops
  - **Volume Control** (Number, 0–100)
  - **Mute** (Switch)
  - **Set as Default Sink** (Button)
  - **Pair / Unpair** (Buttons, under Configuration category)
  - **Connection Status** (Binary Sensor with JSON attributes)
- **Configurable Behaviour**: Poll interval, MQTT base topic, auto-reconnect, and per-device options are all configurable from the add-on dashboard.

---

## Prerequisites

Before installing this add-on, **pair your Bluetooth speaker(s)** with your Home Assistant host. This add-on can reconnect, control, and monitor paired devices — but it cannot perform an initial pairing from scratch with an unknown device.

Pair devices via **Settings > System > Hardware > Bluetooth** or via the HA Bluetooth integration.

---

## Installation

1. Click the **Add Repository** button above, or manually add the repository URL:
   - Go to **Settings > Add-ons > Add-on Store**
   - Click the 3-dot menu → **Repositories**
   - Paste `https://github.com/aalaei/ha-addon-btaudio2mqtt` and click **Add**
2. Find **Bluetooth Audio MQTT Bridge** in the store and click **Install**.
3. After installation, go to the **Configuration** tab before starting.

---

## Configuration

All options are set via the **Configuration** tab in the add-on UI.

| Option | Type | Default | Description |
|---|---|---|---|
| `mqtt_base_topic` | string | `btaudio2mqtt` | Root MQTT topic for all devices |
| `poll_interval` | int | `10` | How often (seconds) to poll and publish device state |
| `auto_reconnect` | bool | `true` | Automatically reconnect if a device drops unexpectedly |
| `devices` | list | `[]` | List of Bluetooth speakers to manage |

Each entry in `devices` supports:

| Option | Type | Required | Default | Description |
|---|---|---|---|---|
| `mac_address` | string | Yes | — | Bluetooth MAC address (e.g. `D0:C9:07:90:57:6B`) |
| `friendly_name` | string | Yes | — | Display name in Home Assistant |
| `auto_connect` | bool | No | `false` | Attempt to connect automatically on add-on start |
| `reconnect_attempts` | int | No | `3` | Number of connect retries before giving up |

**Example configuration:**

```json
{
  "mqtt_base_topic": "btaudio2mqtt",
  "poll_interval": 10,
  "auto_reconnect": true,
  "devices": [
    {
      "mac_address": "D0:C9:07:90:57:6B",
      "friendly_name": "Govee Speaker",
      "auto_connect": true,
      "reconnect_attempts": 3
    },
    {
      "mac_address": "AA:BB:CC:DD:EE:FF",
      "friendly_name": "Living Room Soundbar",
      "auto_connect": false,
      "reconnect_attempts": 5
    }
  ]
}
```

---

## MQTT Topic Structure

Each device uses the following topic layout (replace `{name}` with the lowercase, underscore-separated `friendly_name`):

| Topic | Direction | Description |
|---|---|---|
| `{base}/{name}/state/connection` | Published | `ON` / `OFF` connection state |
| `{base}/{name}/state/volume` | Published | Current volume (0–100) |
| `{base}/{name}/state/mute` | Published | `ON` / `OFF` mute state |
| `{base}/{name}/status` | Published | JSON blob with full status |
| `{base}/{name}/set/connect` | Subscribe | `ON` to connect, `OFF` to disconnect |
| `{base}/{name}/set/volume` | Subscribe | Integer 0–100 |
| `{base}/{name}/set/mute` | Subscribe | `ON` / `OFF` |
| `{base}/{name}/set/setsink` | Subscribe | `PRESS` to set as default audio output |
| `{base}/{name}/set/pair` | Subscribe | `PRESS` to pair and trust device |
| `{base}/{name}/set/unpair` | Subscribe | `PRESS` to remove device |

---

## How It Works

- **Bluetooth state**: `bluetoothctl info {MAC}` is used as the primary check — this reads directly from the BlueZ daemon and is not affected by stale PulseAudio state.
- **Audio state** (volume, mute, default sink): Read via the HA Supervisor audio API (`/audio/info`), which returns structured data for all PulseAudio outputs.
- **Set commands**: Routed back through the Supervisor API (`/audio/volume/output`, `/audio/mute/output`, `/audio/default/output`).
- **Connect/Disconnect**: Run via `bluetoothctl connect/disconnect` piped as a subprocess, followed by an audio reload to re-register the PulseAudio card.

---

## Acknowledgements

This add-on was inspired by the work of [adrgumula](https://github.com/adrgumula) on [HomeAssitantBluetoothSpeaker](https://github.com/adrgumula/HomeAssitantBluetoothSpeaker). Thank you for the original concept and foundation.

---

## License

This project is licensed under the MIT License — see the `LICENSE` file for details.
