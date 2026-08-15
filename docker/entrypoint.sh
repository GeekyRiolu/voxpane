#!/usr/bin/env sh
# voxpane container entrypoint: seed a sane config + fetch the Piper voice on
# first run (kept on the /models volume, not baked into the image), then exec.
set -eu

CONF_DIR="${XDG_CONFIG_HOME:-/config}/voxpane"
CONF="${CONF_DIR}/config.toml"
VOICE="${VOXPANE_PIPER_DIR}/${VOXPANE_PIPER_VOICE}.onnx"

# 1. Seed a container config once (points STT/TTS at the /models volume). A
#    user-mounted config.toml is respected — we only write if none exists.
if [ ! -f "$CONF" ]; then
    mkdir -p "$CONF_DIR"
    cat > "$CONF" <<EOF
# voxpane container config (auto-generated on first run; edit freely).
[whisper]
daemon_model = "small"            # faster-whisper, auto-downloaded to \$HF_HOME

[speak]
backends = ["bluetooth", "notify"]

[speak.bluetooth]
piper_model = "${VOICE}"          # on-device neural TTS
sink = ""                         # "" = default sink (host speaker / your Echo)
EOF
fi

# 2. Fetch the Piper voice once. Best-effort: if there's no network yet, voxpane
#    just falls back to the notify backend until it's downloaded.
if [ ! -f "$VOICE" ] && command -v curl >/dev/null 2>&1; then
    echo "voxpane: fetching Piper voice '${VOXPANE_PIPER_VOICE}' -> ${VOXPANE_PIPER_DIR}" >&2
    mkdir -p "${VOXPANE_PIPER_DIR}"
    base="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium"
    if curl -fsSL "${base}/${VOXPANE_PIPER_VOICE}.onnx" -o "${VOICE}.part"; then
        curl -fsSL "${base}/${VOXPANE_PIPER_VOICE}.onnx.json" -o "${VOICE}.json" || true
        mv "${VOICE}.part" "$VOICE"
    else
        rm -f "${VOICE}.part"
        echo "voxpane: voice download failed (offline?) — TTS will use the notify fallback" >&2
    fi
fi

# 3. Hand off to the CLI. `docker run voxpane <cmd>` -> voxpane <cmd>.
exec voxpane "$@"
