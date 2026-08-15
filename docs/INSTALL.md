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

The core packages (audio, notifications, tmux, the whisper glue) are the same
everywhere; the **focus / typing / clipboard** tools depend on your desktop — see
[Desktop support](#desktop-support) just below.

Arch (or a derivative):

```bash
sudo pacman -S --needed pipewire pipewire-pulse pipewire-audio wireplumber \
  bluez bluez-utils libnotify jq tmux uv sox \
  wl-clipboard wtype            # Hyprland/Sway; on X11 use xclip + xdotool instead
```

On Debian/Ubuntu use `apt`, on Fedora `dnf` — the package names are nearly
identical (`pipewire`, `wl-clipboard`, `wtype`, `libnotify-bin`/`libnotify`, …).
`voxpane doctor` detects your package manager and prints the exact install command
for anything missing. `sox` pads audio with lead-in silence (see §6).

## Desktop support

voxpane auto-detects your session (override with `[desktop] backend` in
`config.toml`) and routes window-focus, typing, and clipboard to the right tools.
**Audio, media-pause, notifications, tmux delivery, and spoken summaries work on
every desktop** — only these three differ:

| Desktop | Focus gate | Types via | Clipboard | Pixel pet | Status |
|---|---|---|---|---|---|
| **Hyprland** | `hyprctl` | `wtype` | `wl-copy` | ✓ | **tested** |
| **Sway** | `swaymsg` | `wtype` | `wl-copy` | ✓ | experimental |
| **X11** (XFCE, i3, …) | `xdotool` | `xdotool` | `xclip`/`xsel` | — | experimental |
| **GNOME/KDE Wayland** | — (relaxed) | `ydotool`¹ | `wl-copy` | — | experimental |

¹ `ydotool` needs its daemon (`ydotoold`) running and there's no focused-window API
on plain Wayland, so typing is best-effort — the transcript always lands on the
clipboard as a fallback (Ctrl+Shift+V to paste).

- **Pixel pet** (`voxpane overlay`) uses the wlr-layer-shell protocol, so it only
  appears on Hyprland/Sway. Elsewhere voxpane runs headless — voice and dictation
  are unaffected.
- **Keybinds**: `voxpane install-bindings` writes the SUPER ALT V bind on Hyprland
  and Sway; on other desktops it prints the two shortcuts to add by hand in your
  system keyboard settings.
- Only **Hyprland** is exercised on the author's machine. Sway/X11/GNOME/KDE are
  written to spec and unit-tested but ship **experimental** — please report what
  works (or doesn't) via a GitHub issue.

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

## 6b. Echo cancellation — hands-free "talk over audio" (optional)

Hands-free listen mode keeps the mic open, so it can hear whatever your speakers
play (a YouTube video, the Dot itself). voxpane handles this two ways:

1. **Default — pause while audio plays** (`[listen] pause_on_playback = true`).
   The mic is ignored whenever something is actively playing; **pause your video
   and it listens again.** No setup. Combined with the focus gate (only listen
   when the Claude window is focused), this covers the common case.

2. **Advanced — echo cancellation** (talk *over* audio). PipeWire can subtract
   the speaker signal from the mic so only your voice remains:

   ```bash
   # create an echo-cancelled virtual mic + sink (webrtc AEC)
   pactl load-module module-echo-cancel aec_method=webrtc \
     source_name=voxpane_ec source_master=@DEFAULT_SOURCE@ \
     sink_name=voxpane_ec_sink sink_master=@DEFAULT_SINK@ \
     use_master_format=1
   ```

   Route the audio you want cancelled through `voxpane_ec_sink` (e.g. set it as
   the default output), then point voxpane's capture at the cleaned source in
   `~/.config/voxpane/config.toml`:

   ```toml
   [audio]
   source = "voxpane_ec"
   ```

   Make it permanent with a drop-in under `~/.config/pipewire/pipewire.conf.d/`.
   AEC quality varies; if it's fiddly, the default pause-on-playback is the
   reliable path.

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
