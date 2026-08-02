# Installing voxpane

`./install.sh` automates most of this. But a few steps deserve your eyes — the
microphone check, the whisper.cpp build, and choosing how your Echo speaks — so
here is the full manual path. Skip to whatever `voxpane doctor` is complaining
about.

> Target platform: **Arch Linux** on a **Wayland / Hyprland** session.

## 1. The one-command path

```bash
git clone https://github.com/GeekyRiolu/voxpane.git
cd voxpane
./install.sh          # add --dry-run to preview, --yes to skip prompts
```

`install.sh` handles §2–§4 and §6–§7 below for you (with confirmation) and ends
by running `voxpane doctor`. The manual steps that remain are §1.5 (choosing your
Echo output route) and the mic sanity check in §2.

---

## 2. Confirm your microphone

```bash
wpctl status | sed -n '/Sources:/,/^$/p'
```

Note the ID and name of your default source (`*` marks it). Your laptop's
built-in mic does the listening — the Echo cannot act as an input device over
Bluetooth.

```bash
pw-record --rate=16000 --channels=1 --format=s16 /tmp/mictest.wav
# speak, then Ctrl-C
pw-play /tmp/mictest.wav
```

If it's quiet or clipped: `wpctl set-volume @DEFAULT_AUDIO_SOURCE@ 0.9`.

## 3. System packages

```bash
sudo pacman -S --needed pipewire pipewire-pulse pipewire-audio wireplumber \
  bluez bluez-utils wl-clipboard wtype libnotify jq tmux uv sox
```

`wtype` is the Wayland-native keystroke injector — `xdotool` will **not** work
under Hyprland. `sox` pads audio with lead-in silence (see §6).

## 4. whisper.cpp

```bash
yay -S whisper.cpp        # provides `whisper-cli`
```

Or from source, with Vulkan if you have a usable GPU:

```bash
git clone https://github.com/ggml-org/whisper.cpp ~/src/whisper.cpp
cd ~/src/whisper.cpp
cmake -B build -DGGML_VULKAN=1
cmake --build build -j --config Release
```

## 4b. The Whisper model

```bash
mkdir -p ~/.local/share/whisper-models && cd ~/.local/share/whisper-models
curl -LO https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo-q5_0.bin
```

Sanity check and **time it** — this number drives your latency expectations:

```bash
time whisper-cli -m ~/.local/share/whisper-models/ggml-large-v3-turbo-q5_0.bin \
  -f /tmp/mictest.wav -l en -np -nt
```

## 5. Pick your Echo output route

You have two ways to make the Dot speak. Decide now — it changes what you
install. **Try Route A first**; it's the one that sounds like Alexa.

### Route A — unofficial Alexa API (Alexa's real voice, over WiFi)

Amazon's internal web API. No Bluetooth, works with the laptop lid shut, targets
a Dot by name.

```bash
uv tool install alexa-cli          # or: git clone https://github.com/xeb/alexa-cli
alexa login                        # prints a sign-in URL; paste back the maplanding URL
alexa devices                      # confirm your Dot is listed and online
alexa say "voxpane is online" --device "<your dot name>"
```

If that last command speaks, you're set. **Tradeoff:** this endpoint is
unofficial and has broken before (there are 2026 reports of `speak` failing).
voxpane treats it as the *preferred* backend, not the only one — it falls through
to Route B and then to a notification.

### Route B — local TTS over Bluetooth (always works, not Alexa's voice)

The Dot is a dumb A2DP speaker; Piper synthesises on your laptop.

```bash
yay -S piper-tts
mkdir -p ~/.local/share/piper && cd ~/.local/share/piper
# grab a voice from https://github.com/rhasspy/piper/blob/master/VOICES.md
```

Pair the Dot: say *"Alexa, pair Bluetooth"*, then in `bluetoothctl`: `scan on`,
`pair <MAC>`, `trust <MAC>`, `connect <MAC>`. Find the sink with
`wpctl status | grep bluez`.

## 6. Route B clipping fix

A2DP links idle out. The first ~500–800 ms after a silent gap gets swallowed, so
"Done — three files changed" becomes "ee files changed." voxpane pads every clip
with lead-in silence (`speak.bluetooth.lead_silence_ms`, default 800). The
manual equivalent:

```bash
sox -n -r 22050 -c 1 /tmp/pad.wav trim 0.0 0.8
sox /tmp/pad.wav speech.wav out.wav
```

## 7. Install the CLI & config

```bash
uv tool install --from . voxpane     # or: pipx install .
mkdir -p ~/.config/voxpane
cp config/config.default.toml   ~/.config/voxpane/config.toml
cp config/commands.default.toml ~/.config/voxpane/commands.toml
```

Edit `~/.config/voxpane/config.toml` — at least `speak.alexa.device` (your Echo's
name) and `delivery.tmux_target` (default `claude:0.0`).

## 8. Verify

```bash
voxpane doctor
```

Green across the board? You're ready. Then:

```bash
voxpane install-bindings     # bind SUPER ALT V
voxpane install-hooks        # wire spoken summaries into Claude Code
```

## Definition of done

> Fresh clone → `./install.sh` → `voxpane doctor` passes → **SUPER ALT V** twice →
> spoken prompt appears in the Claude Code pane → press Enter → walk away → the
> Dot says what Claude did.
