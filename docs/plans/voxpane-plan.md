# voxpane — talk to Claude Code, and have your Echo talk back

Press a key, speak a prompt, and it lands in your Claude Code pane. When Claude
finishes the turn, your Echo Dot reads out what it did.

Speech in is fully local (Whisper). Speech out goes to a real Echo Dot.

---

# PART 1 — Manual setup (do this yourself first, ~15 min)

Do not hand Part 1 to Claude Code. These steps verify hardware and pull large
binaries; you want eyes on them.

## 1.1 Confirm your microphone

```bash
wpctl status | sed -n '/Sources:/,/^$/p'
```

Note the ID and name of your default source (`*` marks it). Your laptop's built-in
mic does the listening — the Echo cannot act as an input device over Bluetooth.

```bash
pw-record --rate=16000 --channels=1 --format=s16 /tmp/mictest.wav
# speak, then Ctrl-C
pw-play /tmp/mictest.wav
```

If it's quiet or clipped, try `wpctl set-volume @DEFAULT_AUDIO_SOURCE@ 0.9`.

## 1.2 Install packages

```bash
sudo pacman -S --needed pipewire pipewire-pulse pipewire-audio wireplumber \
  bluez bluez-utils wl-clipboard wtype libnotify jq tmux uv sox
```

`wtype` is the Wayland-native keystroke injector — `xdotool` will not work under
Hyprland. `sox` is for padding audio with lead-in silence (see §1.6).

## 1.3 Install whisper.cpp

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

## 1.4 Download the STT model

```bash
mkdir -p ~/.local/share/whisper-models && cd ~/.local/share/whisper-models
curl -LO https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo-q5_0.bin
```

Sanity check and **time it**:

```bash
time whisper-cli -m ~/.local/share/whisper-models/ggml-large-v3-turbo-q5_0.bin \
  -f /tmp/mictest.wav -l en -np -nt
```

## 1.5 Pick your Echo output route

You have two ways to make the Dot speak. Decide now, because it changes what you
install. **Try Route A first** — it's the one that sounds like Alexa.

### Route A — unofficial Alexa API (Alexa's real voice, over WiFi)

Uses Amazon's internal web API. No Bluetooth, works even with the laptop lid shut,
targets a specific Dot by name.

```bash
uv tool install alexa-cli          # or: git clone https://github.com/xeb/alexa-cli
alexa login                        # prints a sign-in URL, paste back the maplanding URL
alexa devices                      # confirm your Dot appears and is online
alexa say "voxpane is online" --device "<your dot name>"
```

If that last command speaks, you're done. **Understand the tradeoff:** this endpoint
is unofficial and has broken before — there are 2026 reports of `speak` failing. The
project treats it as the preferred backend, not the only one.

### Route B — local TTS over Bluetooth (always works, not Alexa's voice)

The Dot is a dumb A2DP speaker; Piper synthesizes on your laptop.

```bash
yay -S piper-tts
mkdir -p ~/.local/share/piper && cd ~/.local/share/piper
# grab a voice from https://github.com/rhasspy/piper/blob/master/VOICES.md
```

Pair the Dot: say *"Alexa, pair Bluetooth"*, then `bluetoothctl` → `scan on`,
`pair <MAC>`, `trust <MAC>`, `connect <MAC>`. Find the sink with
`wpctl status | grep bluez`.

## 1.6 If you use Route B, note the clipping problem

A2DP links idle out. The first ~500–800ms after a silent gap gets swallowed, so
"Done — three files changed" becomes "ee files changed." Pad every clip with lead-in
silence:

```bash
sox -n -r 22050 -c 1 /tmp/pad.wav trim 0.0 0.8
sox /tmp/pad.wav speech.wav out.wav
```

The build spec bakes this in as `lead_silence_ms`.

**Stop here.** Everything below is the build spec.

---

# PART 2 — Build spec for Claude Code

## Status

**All milestones M0–M9 are implemented and unit-tested** (92 tests), with the
sole exception of M9's WebRTC-VAD silence auto-stop, which is deferred. Config
defaults, the three hook scripts, `install.sh`, packaging, the systemd unit and
the waybar module are all in place. See the `README.md` roadmap for the live
status table. What remains is hardware setup (per Part 1) and, optionally, the
VAD auto-stop.

## Kickoff prompt

The bundled skill (`.claude/skills/voxpane/`) auto-activates when you open the
repo in Claude Code and already knows the build loop and the constraints. The
one remaining feature:

> Read `docs/plans/voxpane-plan.md`. Everything is built except M9's VAD silence
> auto-stop — implement that (webrtcvad; stop recording after ~2 s of quiet, in
> `recorder.py`), keep the pure modules pure and fully tested, then stop and tell
> me how to test. Ask before installing anything with pacman/yay.

## What this is

A bidirectional voice layer around a terminal coding agent:

- **Inbound:** push-to-talk → local Whisper → command-dictionary rewriting → injected
  into a tmux pane running Claude Code.
- **Outbound:** Claude Code lifecycle hooks → activity ledger → spoken summary on an
  Echo Dot when a turn completes.

## Non-goals

- No wake word, no always-on listening.
- No cloud STT. Ever. Audio does not leave the machine.
- Not a general voice-control system (that's Talon's job).
- Not an Alexa Skill. Nothing here is published to Amazon.

## Architecture

```
INBOUND
  [SUPER ALT V]
       │ toggle
       ▼
  voxpane CLI ──unix socket──▶ voxpaned (model resident in RAM)
       │                            │
  pw-record → /tmp/vp-<ts>.wav ─────┘
                                    │ transcribe
                                    │ postprocess (command dictionary)
                                    ▼
                     tmux send-keys -l → Claude Code pane
                              (never auto-submits)

OUTBOUND
  Claude Code
       │
       ├─ PostToolUse hook ──▶ append to ledger.jsonl  (files touched, cmds run)
       │
       └─ Stop hook ─────────▶ voxpane speak --from-hook
                                    │
                              gate: did this turn do real work?
                                    │ yes
                              summarize: ledger facts + one-line LLM polish
                                    │
                              speaker backend chain:
                                 alexa → bluetooth → notify
                                    │
                                    ▼
                                 Echo Dot
```

## Repo layout

```
voxpane/
├── install.sh              # one-command setup (deps, model, CLI, config, doctor)
├── pyproject.toml          # hatchling; zero core deps; extras: daemon, dev
├── Makefile                # install / dev / doctor / test / lint / fmt
├── bin/voxpane             # run from a clone without installing
├── src/voxpane/
│   ├── cli.py              # argparse dispatch (doctor real; rest -> milestone stubs)
│   ├── config.py           # load defaults + deep-merge user config
│   ├── paths.py            # XDG locations (added — nothing hard-codes a path)
│   ├── doctor.py           # M0, implemented (split out of cli for testability)
│   ├── recorder.py
│   ├── transcriber.py
│   ├── postprocess.py
│   ├── deliver.py          # tmux / focus / clipboard
│   ├── ledger.py           # append + read + prune the per-session activity log
│   ├── summarize.py        # ledger facts -> spoken sentence
│   ├── notify.py           # desktop toasts (recording UX + speaker floor)
│   ├── daemon.py
│   └── speakers/
│       ├── base.py         # Speaker interface + SpeakerError
│       ├── alexa.py        # alexa-cli subprocess
│       ├── bluetooth.py    # piper -> sox pad -> pw-play --target
│       └── notify.py       # fallback: desktop notification only
├── config/
│   ├── config.default.toml
│   └── commands.default.toml
├── hooks/
│   ├── voxpane-post-tool.sh
│   └── voxpane-stop.sh
├── hypr/bindings.snippet
├── systemd/voxpaned.service   # --user unit for the M5 daemon
├── tests/                  # + fixtures/{audio,hooks}/
├── docs/
│   ├── ARCHITECTURE.md
│   ├── INSTALL.md
│   ├── CONTRIBUTING.md
│   └── plans/voxpane-plan.md   # this file
├── .claude/skills/voxpane/     # the build-&-setup skill
└── README.md
```

Two modules were added beyond the original sketch, both for testability and to
keep paths/defaults out of the call sites: `paths.py` (all XDG locations) and
`doctor.py` (M0, split out of `cli.py`). `cli.py` stays a thin dispatcher.

State in `$XDG_RUNTIME_DIR/voxpane/` (state.json, record.pid, daemon.sock,
`ledger-<session_id>.jsonl`, speak.lock). Config in `~/.config/voxpane/`. Logs in
`~/.local/state/voxpane/log`.

## Constraints (read before designing anything)

**Inbound**

- Wayland/Hyprland. `xdotool`/`xbindkeys` do not work. Use `wtype` and `wl-copy`.
- **Stop `pw-record` with SIGINT, not SIGKILL.** SIGKILL leaves the WAV header
  unfinalized and the file unreadable. `pkill -INT -f pw-record`.
- **`tmux send-keys` needs `-l`** for literal text, or words like `Enter` and `Space`
  are interpreted as key names.
- **Never auto-submit by default.** Text lands in the input buffer; the user presses
  Enter. Submitting a mis-transcription is worse than a wasted keystroke.
- Omarchy updates can overwrite `~/.config/hypr/bindings.conf` (upstream issue
  #1802). Keep the binding in a repo-tracked snippet with an idempotent re-apply
  command.
- Omarchy's binding format varies by version: newer builds use `bindings.lua` with an
  `o.bind(...)` helper, older ones `bindings.conf` with `bindd = ...`. Detect which
  exists and match the surrounding syntax rather than assuming.

**Outbound**

- **The Stop hook fires on every turn end**, including when Claude just asks a
  clarifying question. Speaking every time is unbearable within ten minutes. Gating
  is not optional — see M6.
- **Guard on `stop_hook_active`.** If true, exit 0 immediately. Ignoring this risks a
  hook loop.
- **The hook must not block Claude Code.** Emit `{"async":true}` as the first stdout
  line and background the work, or the user watches the agent hang while Piper
  synthesizes.
- **`last_assistant_message` is markdown**, frequently with code fences, file paths,
  and bullet lists. Reading it verbatim produces "backtick backtick backtick python".
  It must be reduced to spoken prose, never passed through raw.
- **Cap spoken text at ~240 characters.** Long TTS over the unofficial Alexa endpoint
  is unreliable and long spoken summaries are useless anyway.
- **Concurrent sessions are normal.** Two Claude Code panes finishing at once must
  not talk over each other. Serialize through a lock, and prefix each utterance with
  the project directory name when more than one session is active.
- The Alexa backend needs network and valid auth. It **will** fail eventually. Every
  failure path falls through to the next backend, and the final fallback
  (`notify`) must never fail.

## Config schema (`config.default.toml`)

```toml
[audio]
source = "default"
rate = 16000
max_seconds = 120

[whisper]
binary = "whisper-cli"
model = "~/.local/share/whisper-models/ggml-large-v3-turbo-q5_0.bin"
language = "en"
threads = 0
initial_prompt = """
Claude Code, tmux, Hyprland, Omarchy, Arch Linux, Wayland, Neovim, git rebase,
async await, TypeScript, Python, JSON, YAML, npm, uv, Docker, Postgres, API,
refactor, stdout, stderr, CLI, repo, commit, branch, merge conflict.
"""

[delivery]
mode = "tmux"
tmux_target = "claude:0.0"
auto_submit = false

[behavior]
strip_filler = true
trailing_submit_phrase = "send it"

[speak]
enabled = true
backends = ["alexa", "bluetooth", "notify"]   # tried in order
max_chars = 240
prefix_project = "auto"        # auto | always | never

[speak.gate]
min_turn_seconds = 25          # short turns stay silent
require_tool_use = true        # must have edited/run something
skip_if_question = true        # suppress when the turn ends in a question to the user
quiet_hours = "23:00-08:00"

[speak.alexa]
command = "alexa"
device = "Office Dot"
mode = "say"                   # say (no chime) | announce (chime)

[speak.bluetooth]
sink = ""                      # empty = autodetect bluez_output.*
piper_model = "~/.local/share/piper/en_GB-alba-medium.onnx"
lead_silence_ms = 800

[summary]
mode = "hybrid"                # facts | llm | hybrid
llm_command = "claude -p --model haiku --output-format text"
llm_timeout_seconds = 8
```

`whisper.initial_prompt` biases the decoder toward your vocabulary. It caps at 224
tokens — validate and warn past that.

## Command dictionary (`commands.default.toml`)

Applied in order: exact-phrase replacements, then key actions, then cleanup.
Case-insensitive, word-boundary anchored.

```toml
[text]
"slash clear"     = "/clear"
"slash compact"   = "/compact"
"slash model"     = "/model"
"slash init"      = "/init"
"slash review"    = "/review"
"open paren"      = "("
"close paren"     = ")"
"open brace"      = "{"
"close brace"     = "}"
"backtick"        = "`"
"triple backtick" = "```"
"new line"        = "\n"
"at file"         = "@"

[keys]
"escape escape"   = "Escape Escape"
"scratch that"    = "C-u"

[transforms]
"camel case"      = "camel"     # "camel case user profile" -> userProfile
"snake case"      = "snake"
"kebab case"      = "kebab"
"pascal case"     = "pascal"

[fixups]                        # common Whisper mishearings
"get commit"      = "git commit"
"get push"        = "git push"
"pseudo"          = "sudo"
"no JS"           = "Node.js"
```

Slash commands should match at the **start of the utterance only**, so "the slash
clear command is useful" stays literal.

## The activity ledger

`PostToolUse` hooks append one JSON line per tool call to
`$XDG_RUNTIME_DIR/voxpane/ledger-<session_id>.jsonl`:

```json
{"ts": 1754130000, "tool": "Edit", "path": "src/voxpane/cli.py"}
{"ts": 1754130012, "tool": "Bash", "cmd": "uv run pytest", "exit": 0}
{"ts": 1754130044, "tool": "Write", "path": "tests/test_postprocess.py"}
```

This exists because **facts beat prose**. "Edited four files and ran the tests, all
passing" is derived deterministically from the ledger and is more useful spoken aloud
than any summary of Claude's markdown. The LLM pass only adds a clause of intent on
top. The ledger is truncated at Stop, after the summary is built.

## Summarizer

`mode = "facts"` — template from the ledger alone, no network:
> "Four files changed in voxpane. Tests ran clean."

`mode = "llm"` — pipe `last_assistant_message` to `claude -p --model haiku` with a
system prompt demanding one spoken sentence, under 30 words, no markdown, no file
paths read character by character, no code.

`mode = "hybrid"` (default) — facts sentence + LLM clause, LLM call bounded by
`llm_timeout_seconds` and falling back to facts-only on timeout or error.

Post-process for speech in all modes: expand or drop file extensions, collapse paths
to basenames, strip backticks, spell out symbols, cap at `max_chars` on a sentence
boundary.

## Milestones

Implement in order. Stop after each and report how to test.

### M0 — `voxpane doctor`
Checks `pw-record`, `whisper-cli`, `wtype`, `wl-copy`, `tmux`, `notify-send` on PATH;
model file present and >100 MB; default source present and unmuted; runtime dir
writable; tmux target exists if delivery is tmux. Later milestones extend it with
`alexa devices` reachability and bluez sink presence.
**Accept:** pass/fail table with a remediation hint per row; non-zero exit on failure.

### M1 — one-shot inbound
`voxpane start` / `voxpane stop` records, transcribes, prints the transcript and
copies it to the clipboard.
**Accept:** a 15-second spoken paragraph round-trips correctly; stop→clipboard time
is logged.

### M2 — toggle, keybind, feedback
`voxpane toggle` flips state via the state file. Notifications: persistent
"🎙 Recording…", replaced (same `--replace-id`) by "⏳ Transcribing…" then a two-line
preview. `voxpane install-bindings` is idempotent, backs up the existing file, and
detects `.lua` vs `.conf`. Suggest `SUPER ALT, V`.
**Accept:** two keypresses from any window put the transcript in the clipboard with
no terminal open.

### M3 — delivery backends
`tmux` (`send-keys -t <target> -l --`, no Enter unless `auto_submit`; fall back to
clipboard with a warning if the pane is gone), `focus` (`wl-copy` then
`wtype -M ctrl -M shift -k v -m shift -m ctrl` with a configurable ~80ms pre-delay),
`clipboard`.
**Accept:** with Claude Code in a tmux pane on another workspace, dictation lands in
its input box without stealing focus.

### M4 — post-processing
`postprocess.py` implementing the dictionary, filler stripping, and the
trailing-submit phrase (strip "send it" and set auto-submit for that utterance only).
**Accept:** `tests/test_postprocess.py` covers every dictionary category, plus a
mid-sentence match that should *not* fire.

### M5 — daemon
`voxpaned` holds the model in memory behind a unix socket. Switch to `faster-whisper`
(`large-v3-turbo`, `compute_type="int8"` on CPU) loaded once at startup. The CLI
becomes a thin client and falls back to the M1 subprocess path if the socket is
absent, so the tool never hard-fails. Ship a `systemd --user` unit.
**Accept:** p50 from key-release to delivered text under 1.2s for a 10-second
utterance. Put the number in the README.

### M6 — outbound plumbing (no Echo yet)
`ledger.py`, the two hook scripts, `voxpane install-hooks` (merges into
`~/.claude/settings.json` without clobbering existing hooks — read, merge, write, and
back up first), and the gate logic. Speaker is `notify` only: the summary appears as
a desktop notification.
**Accept:** finishing a real Claude Code turn produces a notification with an accurate
factual summary. A turn where Claude only asks a question produces **nothing**. A
5-second turn produces nothing. Claude Code never visibly stalls waiting on the hook.

### M7 — summarizer
`summarize.py` with all three modes, the speech post-processing rules, and the
character cap.
**Accept:** unit tests feed recorded ledgers plus realistic markdown
`last_assistant_message` payloads (one with a code fence, one with a bullet list, one
with a long file path) and assert the output is plain spoken English under the cap.
Hybrid mode falls back cleanly when `llm_command` is missing or times out.

### M8 — Echo speaker backends
`speakers/alexa.py` and `speakers/bluetooth.py` behind `speakers/base.py`, with the
ordered fallback chain and a lock serializing concurrent utterances. `voxpane speak
"test"` exercises the chain directly. `voxpane doctor` gains Alexa auth and bluez
sink checks.
**Accept:** finishing a turn makes the Dot speak the summary. Killing the network
mid-test falls through to Bluetooth; disconnecting Bluetooth too falls through to a
notification. No path raises.

### M9 — polish (optional)
- Waybar module reading the state file (`return-type: json`, `interval: once` +
  `signal`), red dot while recording, speaker icon while speaking.
- `voxpane vocab --from-repo` — scan `git ls-files` for identifiers, split
  camel/snake case, generate an `initial_prompt` addendum for the current project,
  respecting the 224-token cap.
- Silence auto-stop via WebRTC VAD after 2s of quiet.
- `Notification` hook → short chime on the Dot when Claude is blocked on a permission
  prompt. This is arguably the single most useful outbound event; consider promoting
  it into M8.

## Testing

- `tests/fixtures/audio/` — recorded WAVs (technical dictation, a slash command, a
  long paragraph) so transcription is regression-testable without a mic.
- `tests/fixtures/hooks/` — captured real Stop and PostToolUse stdin payloads.
- Mock every subprocess (`whisper-cli`, `alexa`, `piper`, `pw-play`, `tmux`) in unit
  tests. Keep integration tests behind `VOXPANE_INTEGRATION=1`.
- `postprocess.py`, `summarize.py`, and the gate must be pure and fully unit-tested.
  That's where the bugs will be, and the gate is where the annoyance will be.

## Definition of done

Fresh clone → `./install.sh` → `voxpane doctor` passes → `SUPER ALT V` twice → spoken
prompt appears in the Claude Code pane → press Enter → walk away → the Dot says what
Claude did.
