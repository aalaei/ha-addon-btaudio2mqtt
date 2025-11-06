# Bluetooth Audio MQTT Bridge - Home Assistant Add-on

[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg?style=for-the-badge)](https://github.com/hacs/integration)
![GitHub Release](https://img.shields.io/github/v/release/aalaei/ha-addon-btaudio2mqtt?style=for-the-badge)
![GitHub commits](https://img.shields.io/github/commit-activity/m/aalaei/ha-addon-btaudio2mqtt?style=for-the-badge)

Control multiple Bluetooth speakers and sinks directly from Home Assistant.

This add-on discovers Bluetooth speakers paired with your Home Assistant host, creates a new HA device for each one, and provides entities to control connection, volume, mute, and default sink selection via MQTT.

[![Open your Home Assistant instance and add this repository.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https://github.com/aalaei/ha-addon-btaudio2mqtt)

---

## Features

* **Multi-Device Support**: Configure multiple Bluetooth speakers and control them all.
* **Auto-Discovery**: Each configured speaker gets its own device in Home Assistant via MQTT Discovery.
* **Full Control**: Provides entities for:
    * **Connect/Disconnect** (Switch)
    * **Volume Control** (Number)
    * **Mute** (Switch)
    * **Set as Default Sink** (Button)
    * **Pair / Unpair** (Buttons)
    * **Connection Status** (Binary Sensor)
* **Direct Control**: Uses `pactl` and `bluetoothctl` directly for robust control without shell command dependencies.

## 1. Prerequisites

Before you install this add-on, you **must** pair your Bluetooth speaker(s) with your Home Assistant host system. This add-on can *control* connections, but it cannot perform the initial pairing process if the device is unknown to the host.

You can often pair devices by going to **Settings > Devices & Services > Bluetooth** and adding the device there. Once it's been successfully paired with HA, this add-on will be able to control it.

## 2. Installation

1.  Click the "Add Repository" button above.
2.  Alternatively, navigate to the Home Assistant Add-on Store:
    * Go to **Settings > Add-ons > Add-on Store**.
    * Click the 3-dots menu in the top-right and select **Repositories**.
    * Paste `https://github.com/aalaei/ha-addon-btaudio2mqtt` into the box and click **Add**.
3.  Find the "Bluetooth Audio MQTT Bridge" add-on in the store and click **Install**.
4.  Wait for the installation to complete.

## 3. Configuration

Once installed, you must configure the add-on before starting it.

1.  Go to **Settings > Add-ons > Bluetooth Audio MQTT Bridge**.
2.  Click the **"Configuration"** tab.
3.  Add your speakers to the `devices` list. You must provide a `mac_address` and a `friendly_name` for each one.



**Example `options.json`:**

```json
{
  "devices": [
    {
      "mac_address": "D0:C9:07:90:57:6B",
      "friendly_name": "Govee Speaker"
    },
    {
      "mac_address": "AA:BB:CC:DD:EE:FF",
      "friendly_name": "Living Room Soundbar"
    }
  ]
}
```

## Acknowledgements

This add-on was inspired by and adapted from the work of [adrgumula](https://github.com/adrgumula) on the [HomeAssitantBluetoothSpeaker](https://github.com/adrgumula/HomeAssitantBluetoothSpeaker) repository. Thank you for providing the original foundation and concept!

---

## License

This project is licensed under the MIT License - see the `LICENSE` file for details.