# syntax=docker/dockerfile:1.7
###############################################################################
# voxpane — the local voice engine for Claude Code, containerised.
#
# The image ships the voxpane CLI + Whisper STT (faster-whisper) + Piper TTS.
# Speech models are NOT baked in (they'd bloat the image) — they download once
# to a mounted /models volume. See docs/DOCKER.md for the audio-passthrough run.
#
# Two stages: `builder` assembles an isolated venv from wheels; `runtime` is a
# slim image that just copies that venv + the client tools voxpane shells out to.
###############################################################################

######################## stage 1: build the venv ##############################
FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /src
# Copy only the files the wheel build needs, so edits to code don't bust the
# (expensive) dependency layer below until pyproject actually changes.
COPY pyproject.toml README.md LICENSE ./
COPY config ./config
COPY hooks ./hooks
COPY ui ./ui
COPY src ./src

# voxpane[daemon,listen] pulls faster-whisper (CTranslate2 — no PyTorch) + webrtcvad;
# piper-tts adds the neural TTS. All ship manylinux/arm64 wheels → no compilers.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip && \
    pip install '.[daemon,listen]' 'piper-tts>=1.2.0'

######################## stage 2: slim runtime ################################
FROM python:3.12-slim AS runtime

ARG VERSION=0.1.0
LABEL org.opencontainers.image.title="voxpane" \
      org.opencontainers.image.description="Local voice layer for Claude Code — Whisper STT in, Piper TTS out." \
      org.opencontainers.image.url="https://github.com/GeekyRiolu/voxpane" \
      org.opencontainers.image.source="https://github.com/GeekyRiolu/voxpane" \
      org.opencontainers.image.licenses="GPL-3.0-or-later" \
      org.opencontainers.image.version="${VERSION}"

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    XDG_CONFIG_HOME=/config \
    XDG_RUNTIME_DIR=/run/voxpane \
    HF_HOME=/models/hf \
    VOXPANE_PIPER_DIR=/models/piper \
    VOXPANE_PIPER_VOICE=en_US-lessac-medium

# Runtime deps ONLY — the client tools voxpane invokes:
#   pipewire-bin ....... pw-cat / pw-play / pw-record (mic + speaker via host socket)
#   pulseaudio-utils ... pactl / paplay / parec (PulseAudio fallback + sink control)
#   wtype / wl-clipboard  type into / copy for the focused window (Wayland delivery)
#   playerctl .......... pause media on wake; sox pads TTS; espeak-ng phonemises Piper
#   tini ............... proper PID-1 signal handling for the long-lived daemon/listener
RUN apt-get update && apt-get install -y --no-install-recommends \
        pipewire-bin \
        pulseaudio-utils \
        wtype \
        wl-clipboard \
        playerctl \
        sox \
        espeak-ng \
        tmux \
        libnotify-bin \
        jq \
        tini \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
COPY docker/entrypoint.sh /usr/local/bin/voxpane-entrypoint
RUN chmod +x /usr/local/bin/voxpane-entrypoint

# Non-root, in the audio group for /dev/snd; writable state/model/config dirs.
RUN useradd --create-home --uid 1000 --user-group --groups audio voxpane \
    && install -d -o voxpane -g voxpane /models /models/hf /models/piper /config /run/voxpane
USER voxpane

# tini reaps zombies + forwards signals; entrypoint seeds config + fetches the
# Piper voice on first run, then execs `voxpane <args>`.
ENTRYPOINT ["tini", "--", "voxpane-entrypoint"]
CMD ["doctor"]
