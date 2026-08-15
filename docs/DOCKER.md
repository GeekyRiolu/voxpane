# voxpane in Docker

A multi-arch (amd64 + arm64) image of the voxpane **voice engine**: the CLI,
Whisper STT (`faster-whisper`, CPU/int8, no PyTorch) and Piper TTS. Speech models
aren't baked in — they download once to a `/models` volume, keeping the image lean.

```bash
docker pull ghcr.io/geekyriolu/voxpane:latest      # or <you>/voxpane on Docker Hub
docker run --rm ghcr.io/geekyriolu/voxpane doctor  # check what's wired up
```

## What runs in the container vs on the host

voxpane is a **desktop-integrated** tool. The container is great for the engine;
a few things are inherently host-native:

| Works in the container (with audio passthrough) | Host-native (use `uv tool install`) |
| --- | --- |
| `voxpane doctor` / `daemon` (resident STT) | eww **pixel pet** overlay (host Wayland) |
| `voxpane speak "…"` → Piper TTS to your speaker/Echo | **wake word opens a terminal + `claude`** |
| `voxpane transcribe` / dictation STT | Claude Code **hooks** (they call host `voxpane`) |
| `voxpane vocab`, `ledger`, config, … | typing into the focused window (`wtype` on host) |

TL;DR: containerise it for a clean, reproducible **STT/TTS engine**; for the full
hands-free desktop flow, the native install is the way.

## Run it with your mic + speaker (docker compose)

The engine needs the host's audio. Edit `docker-compose.yml` if your user isn't
UID 1000 (`id -u`), then:

```bash
docker compose up -d           # runs the resident STT daemon
docker compose run --rm voxpane speak "hello from the container"
docker compose logs -f
```

Or the equivalent one-liner (PipeWire host):

```bash
docker run --rm -it \
  --user "$(id -u):$(id -g)" --group-add audio \
  --device /dev/snd \
  -e PULSE_SERVER=unix:/run/voxpane/pulse/native \
  -v "$XDG_RUNTIME_DIR/pipewire-0:/run/voxpane/pipewire-0" \
  -v "$XDG_RUNTIME_DIR/pulse/native:/run/voxpane/pulse/native" \
  -v voxpane-models:/models \
  -v "$HOME/.config/voxpane:/config/voxpane" \
  ghcr.io/geekyriolu/voxpane speak "hello"
```

- **Models** live on the `voxpane-models` volume — first run downloads the Whisper
  model (`small` by default; `~$HF_HOME`) and the Piper voice; both are cached after.
- **Config**: mounting `~/.config/voxpane` reuses your host settings; otherwise a
  sensible container config is seeded on first run.
- Set the model with `[whisper] daemon_model` (`tiny`/`base`/`small`/`large-v3-turbo`)
  and the voice via `VOXPANE_PIPER_VOICE` or `[speak.bluetooth] piper_model`.

## Build it yourself

```bash
docker build -t voxpane:local .            # this arch
docker buildx build --platform linux/amd64,linux/arm64 -t voxpane:local .   # multi-arch
```

Two stages: a `builder` assembles an isolated venv from wheels (no compilers), and
a slim `runtime` copies that venv plus only the client tools voxpane invokes
(`pipewire-bin`, `pulseaudio-utils`, `wtype`, `wl-clipboard`, `playerctl`, `sox`,
`espeak-ng`), runs as a non-root `voxpane` user, and uses `tini` as PID 1.

## Publishing (CI)

`.github/workflows/docker-publish.yml` builds multi-arch on every push to `main`
and every `v*.*.*` tag:

- **GHCR** — always, at `ghcr.io/<owner>/voxpane` (uses the built-in token).
- **Docker Hub** — add repo secrets `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN`
  (a Docker Hub access token) and it also pushes to `<username>/voxpane`.

Tag a release to cut versioned images: `git tag v0.1.0 && git push --tags`.
