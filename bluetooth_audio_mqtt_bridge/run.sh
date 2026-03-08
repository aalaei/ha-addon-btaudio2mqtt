#!/usr/bin/with-contenv bashio

bashio::log.info "Starting Bluetooth Audio MQTT Bridge..."

# Inject MQTT credentials from the Mosquitto add-on service
export MQTT_HOST=$(bashio::services mqtt "host")
export MQTT_USER=$(bashio::services mqtt "username")
export MQTT_PORT=$(bashio::services mqtt "port")
export MQTT_PASSWORD=$(bashio::services mqtt "password")

bashio::log.info "MQTT Host: ${MQTT_HOST}:${MQTT_PORT}"
bashio::log.info "MQTT User: ${MQTT_USER}"

exec python3 -u /run.py
