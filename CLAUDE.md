# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a **Home Assistant add-on** that bridges Bluetooth audio devices (speakers, soundbars) to Home Assistant via MQTT. It discovers paired Bluetooth devices and creates HA entities for each one: connect/disconnect switch, volume, mute, default sink button, and pair/unpair buttons.

The add-on runs inside a Docker container on the HA host, using:
- `bluetoothctl` (BlueZ) for true Bluetooth connection state
- HA Supervisor audio API (`/audio/*`) for PulseAudio volume/mute/sink control
- `paho-mqtt` to publish state and subscribe to commands
- MQTT Discovery to auto-register devices in Home Assistant

## Repository Structure

```
bluetooth_audio_mqtt_bridge/   # The actual add-on (HA uses this directory)
    config.yaml                # Add-on metadata, schema, required privileges
    Dockerfile                 # Alpine-based image with Python, bluez, pulseaudio-utils
    run.sh                     # Entrypoint: injects MQTT credentials via bashio, then runs run.py
    run.py                     # All application logic (single file)
repository.json                # HA add-on repository descriptor
```

## How the Add-on Works

**Startup flow:**
1. `run.sh` reads MQTT credentials from the Mosquitto add-on via `bashio::services mqtt` and exports them as env vars.
2. `run.py` loads `/data/options.json` (the add-on configuration written by HA Supervisor) and creates a `BluetoothSpeaker` instance per device.
3. MQTT client connects; on connect, all MQTT Discovery payloads are published so HA creates the device entities.
4. Devices with `auto_connect: true` attempt to connect in background threads.
5. A polling loop calls `publish_state()` on each speaker every `poll_interval` seconds.

**Connection state detection (important nuance):**
- PulseAudio cards/sinks persist in memory after a BT device disconnects, making the Supervisor audio API unreliable for connection state.
- Primary source of truth: `bluetoothctl info {MAC}` — reads directly from the BlueZ daemon.
- Fallback (if bluetoothctl gives no output): Supervisor API card list + A2DP profile active check.
- If BT reports connected but no PulseAudio card exists, an audio reload is triggered (throttled to once per 30s).

**MQTT command routing:**
- Subscribe pattern: `{base_topic}/+/set/#`
- Topic format: `{base}/{device_name}/set/{command}` where `device_name` is `friendly_name` lowercased with spaces replaced by `_`.
- Commands: `connect` (ON/OFF), `volume` (0–100 integer), `mute` (ON/OFF), `setsink` (PRESS), `pair` (PRESS), `unpair` (PRESS).
- Connect/disconnect run in daemon threads to avoid blocking the MQTT loop.

**Audio control:**
- Volume: POST `/audio/volume/output` with `{"index": sink_index, "volume": 0.0–1.0}` (Supervisor API uses float, HA entities use 0–100 integer — conversion happens in `set_volume` and `get_status`).
- Mute: POST `/audio/mute/output` with `{"index": sink_index, "active": bool}` (field is `active`, not `muted`).
- Default sink: POST `/audio/default/output` with `{"output": sink_name}`.

## Key Environment Variables

| Variable | Source | Purpose |
|---|---|---|
| `SUPERVISOR_TOKEN` | HA Supervisor (auto-injected) | Auth for all `/audio/*` API calls |
| `SUPERVISOR_URL` | HA Supervisor | Base URL for Supervisor API (default: `http://supervisor`) |
| `MQTT_HOST/PORT/USER/PASSWORD` | Set by `run.sh` via bashio | MQTT broker credentials |

## Config File

`/data/options.json` is written by HA Supervisor from the add-on UI. `load_config()` reads it at startup and sets the global `MQTT_BASE_TOPIC`, `POLL_INTERVAL`, and `AUTO_RECONNECT`, then instantiates speakers.

## Local Development Notes

This add-on is designed to run **inside the HA add-on container only** — it requires the HA Supervisor API (token + host network), `bluetoothctl`, and PulseAudio access. There is no test suite or local dev runner.

To iterate:
1. Edit `run.py` or other files in `bluetooth_audio_mqtt_bridge/`.
2. Push to GitHub; install/update the add-on in HA via the add-on store.
3. Watch add-on logs in HA for `print()` output (all output is unbuffered via `-u` flag and `flush=True`).

To test a specific fix quickly without a full rebuild, you can SSH into the HA host, exec into the running container, and modify `/run.py` directly, then restart the add-on.

## Add-on Privileges

`config.yaml` requires `host_dbus: true`, `bluetooth: true`, `audio: true`, `host_network: true`, `SYS_ADMIN` privilege, and `homeassistant_api: true` / `hassio_api: true`. These are all required — do not remove them.
