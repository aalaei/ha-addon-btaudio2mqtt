#!/usr/bin/with-contenv bashio

echo "Starting Bluetooth Audio MQTT Bridge..."

# Get MQTT credentials from HA services
export MQTT_HOST=$(bashio::services mqtt "host")
export MQTT_USER=$(bashio::services mqtt "username")
export MQTT_PORT=$(bashio::services mqtt "port")
export MQTT_PASSWORD=$(bashio::services mqtt "password")

# This is the correct, portable way to access HA's audio system
# This replaces the 'map:' in config.yaml
export PULSE_SERVER=unix:/run/pulse/native

# Log for debugging
bashio::log.info "MQTT Host: ${MQTT_HOST}:${MQTT_PORT}"
bashio::log.info "MQTT User: ${MQTT_USER}"
bashio::log.info "Pulse Server: ${PULSE_SERVER}"

# Run the main script
python3 -u /run.py