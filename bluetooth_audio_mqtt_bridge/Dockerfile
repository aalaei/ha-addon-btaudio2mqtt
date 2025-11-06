ARG BUILD_FROM=ghcr.io/home-assistant/aarch64-base:latest
FROM $BUILD_FROM

ENV LANG=C.UTF-8

RUN apk add --no-cache \
    python3 \
    pulseaudio-utils \
    alsa-utils \
    alsa-plugins-pulse \
    bluez

RUN pip install --break-system-packages paho-mqtt requests

COPY run.py /run.py
COPY run.sh /
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]